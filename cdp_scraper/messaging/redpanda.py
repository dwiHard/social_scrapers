"""Producer Kafka/Redpanda (lazy: tidak ada koneksi/efek samping saat import)."""
import json
import os

from ..logs import get_logger

_log = get_logger("kafka")


def delivery_callback(err, msg):
    if err is not None:
        _log.error(f"Delivery gagal: {err}")
    else:
        _log.debug(f"Delivery berhasil: {msg.topic()} [{msg.partition()}] offset {msg.offset()}")


def chunk_list(items, size):
    size = max(1, int(size))
    items = list(items)
    return [items[i:i + size] for i in range(0, len(items), size)]


class RedpandaProducer:
    """Pembungkus confluent_kafka.Producer. `producer_factory` opsional untuk test."""

    def __init__(self, bootstrap_servers=None, config=None, log=None, producer_factory=None):
        self.config = {"bootstrap.servers": bootstrap_servers
                       or os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")}
        self.config.update(config or {})
        self.log = log or _log
        self._factory = producer_factory
        self._producer = None
        self._failed = False

    @property
    def producer(self):
        if self._producer is None and not self._failed:
            try:
                factory = self._factory
                if factory is None:
                    from confluent_kafka import Producer as factory
                self._producer = factory(self.config)
                self.log.success(f"Producer siap: {self.config['bootstrap.servers']}")
            except Exception as e:
                self._failed = True
                self.log.error(f"Gagal membuat producer: {e}")
        return self._producer

    @property
    def available(self):
        return self.producer is not None

    def send(self, topic, payload, callback=delivery_callback):
        producer = self.producer
        if producer is None:
            return False
        if isinstance(payload, (bytes, bytearray)):
            data = bytes(payload)
        elif isinstance(payload, str):
            data = payload.encode("utf-8")
        else:
            data = json.dumps(payload).encode("utf-8")
        producer.poll(0)
        producer.produce(topic=topic, value=data, callback=callback)
        return True

    def flush(self, timeout=None):
        producer = self.producer
        if producer is not None:
            producer.flush() if timeout is None else producer.flush(timeout)


_default_producer = None


def get_default_producer():
    global _default_producer
    if _default_producer is None:
        _default_producer = RedpandaProducer()
    return _default_producer


def publish_chunks(producer, topic, items, chunk_size=2, build_payload=None, log=None):
    """Bagi `items` per chunk lalu kirim satu pesan per chunk.

    build_payload(chunk) -> dict atau None (None = lewati, dihitung gagal).
    Return {"berhasil": n, "gagal": n}.
    """
    log = log or _log
    stats = {"berhasil": 0, "gagal": 0}
    for chunk in chunk_list(items, chunk_size):
        try:
            payload = build_payload(chunk) if build_payload else {"keywords": chunk}
            if payload is None:
                stats["gagal"] += 1
                continue
            if producer.send(topic, payload):
                stats["berhasil"] += 1
            else:
                stats["gagal"] += 1
        except Exception as e:
            log.error(f"Gagal mengirim chunk ke Kafka: {e}")
            stats["gagal"] += 1
    producer.flush()
    return stats
