from setuptools import setup

setup(
    install_requires=["clang"],
    entry_points={
        "console_scripts": [
            "pycpptool = pycpptool:main"
        ]
    }
)
