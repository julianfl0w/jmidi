#!/usr/bin/env python

from setuptools import setup, find_packages

setup(
    name="jmidi",
    version="1.0",
    description="Julian's MIDI Manager class",
    author="Julian Loiacono",
    author_email="jcloiacon@gmail.com",
    url="https://github.com/julianfl0w/jmidi",
    packages=find_packages(),
    package_data={
        # everything
        "": ["*"]
    },
    include_package_data=True,
)
