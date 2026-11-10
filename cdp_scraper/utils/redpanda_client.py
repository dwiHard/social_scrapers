from config import KAFKA_CONFIG
from logger import log_debug, log_error, log_success


def delivery_callback(err, msg):
    if err is not None:
        log_error(f"Delivery gagal: {err}", job="kafka")
    else:
        log_debug(f"Delivery berhasil: {msg.topic()} [{msg.partition()}] offset {msg.offset()}", job="kafka")


def _create_producer():
    try:
        from confluent_kafka import Producer
        producer = Producer(KAFKA_CONFIG)
        log_success(f"Producer siap: {KAFKA_CONFIG['bootstrap.servers']}", job="kafka")
        return producer
    except Exception as e:
        log_error(f"Gagal membuat producer: {e}", job="kafka")
        return None


kafka_producer = _create_producer()
