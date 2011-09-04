from setuptools import setup, find_packages

setup(
    name = "sonospy",
    description = "UPNP Controller for Sonos renderer",
    version = "",
    author = "",
    packages = ["sonospy", "brisa", "cherrypy"],
    package_dir = {'':"src"},
    install_requires = ["web2py"],
    )
