import os
from glob import glob
from setuptools import setup
from setuptools.extension import Extension
from Cython.Build import cythonize

from cryptrality import __version__

VERSION = __version__.VERSION
DATE = __version__.DATE
AUTHOR = __version__.AUTHOR
MAIL = __version__.MAIL
WEBSITE = __version__.WEBSITE

install_requires = []
with open("requirements.txt", "rt") as requirements:
    for line in requirements:
        install_requires.append(line.strip())


def list_lines(comment):
    for line in comment.strip().split("\n"):
        yield line.strip()


classifier_text = """
    Development Status :: 5 - Production/Stable
    Intended Audience :: Developers
    Operating System :: OS Independent
    License :: OSI Approved :: GNU General Public License v3 (GPLv3)
    Programming Language :: Python :: 3.9
    Topic :: Software Development :: Libraries :: Application Frameworks
    Topic :: Utilities
"""

extensions = []
for source_file in glob("cryptrality/*.pyx"):
    fname, _ = os.path.splitext(os.path.basename(source_file))
    extensions.append(
        Extension(
            "cryptrality.{}".format(fname),
            sources=[source_file],
        )
    )
for source_file in glob("cryptrality/exchanges/*.pyx"):
    fname, _ = os.path.splitext(os.path.basename(source_file))
    extensions.append(
        Extension(
            "cryptrality.exchanges.{}".format(fname),
            sources=[source_file],
        )
    )
for source_file in glob("cryptrality/subcommands/*.pyx"):
    fname, _ = os.path.splitext(os.path.basename(source_file))
    extensions.append(
        Extension(
            "cryptrality.subcommands.{}".format(fname),
            sources=[source_file],
        )
    )

print(extensions)
setup(
    name="cryptrality",
    python_requires=">3.7.0",
    version=VERSION,
    description=("Easily setup trading bots"),
    long_description="None yet",
    author=AUTHOR,
    author_email=MAIL,
    url=WEBSITE,
    license="GPLv3",
    packages=["cryptrality", "cryptrality.exchanges", "cryptrality.subcommands"],
    test_suite="test",
    entry_points={"console_scripts": ["cryptrality = cryptrality.commands:main"]},
    ext_modules=cythonize(extensions),
    zip_safe=False,
    install_requires=install_requires,
    classifiers=list(list_lines(classifier_text)),
    keywords="trading",
    package_data={"static": ["*"], "templates": ["*.html"]},
)
