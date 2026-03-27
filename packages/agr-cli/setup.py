from setuptools import find_packages, setup

setup(
    name="agr-cli",
    version="0.1.0",
    packages=find_packages(),
    install_requires=["agr-sdk>=0.1.0"],
    entry_points={"console_scripts": ["agr=agr_cli.main:run"]},
    python_requires=">=3.12",
    description="AGR CLI — lightweight command line interface for AGR platform",
)
