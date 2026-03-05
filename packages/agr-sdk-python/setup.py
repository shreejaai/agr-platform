from setuptools import find_packages, setup

setup(
    name="agr-sdk",
    version="0.1.0",
    packages=find_packages(),
    install_requires=["httpx>=0.25.0"],
    python_requires=">=3.12",
    description="AGR Python SDK — governance layer for AI agents",
)
