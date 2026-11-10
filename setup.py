from pathlib import Path

from setuptools import find_packages, setup

namespace = {}
exec((Path(__file__).parent / "cdp_scraper" / "_version.py").read_text(), namespace)

setup(
    name='cdp_scraper',
    version=namespace["__version__"],
    description='Core CDP Browser Automation and Utils Provider',
    long_description=(Path(__file__).parent / "README.md").read_text(encoding="utf-8"),
    long_description_content_type="text/markdown",
    author='Dwi Hardiyanto',
    packages=find_packages(exclude=["tests", "tests.*", "examples", "examples.*"]),
    install_requires=["playwright>=1.57.0"],
    extras_require={
        "patchright": ["patchright"],
        "kafka": ["confluent-kafka"],
    },
    python_requires='>=3.8',
)
