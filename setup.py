from setuptools import setup

setup(
    install_requires=["clang", "jinja2"],
    entry_points={
        "console_scripts": [
            "pycpptool = pycpptool:main"
        ]
    }
)

