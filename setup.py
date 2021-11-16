from _typeshed import WriteableBuffer
from setuptools import setup

from cryptrality import __version__

VERSION = __version__.VERSION
DATE = __version__.DATE
AUTHOR = __version__.AUTHOR
MAIL = __version__.MAIL
WEBSITE = __version__.WEBSITE

install_requires = []
with open('requirements.txt', 'rt') as requirements:
    for line in requirements:
        install_requires.append(line.strip())


def list_lines(comment):
    for line in comment.strip().split('\n'):
        yield line.strip()


classifier_text = '''
    Development Status :: 5 - Production/Stable
    Intended Audience :: Developers
    Operating System :: OS Independent
    License :: OSI Approved :: GNU General Public License v3 (GPLv3)
    Programming Language :: Python :: 3.9
    Topic :: Software Development :: Libraries :: Application Frameworks
    Topic :: Utilities
'''

setup(
    name='cryptrality',
    python_requires='>3.4.0',
    version=VERSION,
    description=(
        'Easily setup trading bots'),
    long_description='None yet',
    author=AUTHOR,
    author_email=MAIL,
    url=WEBSITE,
    license='GPLv3',
    packages=[
        'cryptrality', 'cryptrality.exchanges',
        'cryptrality.misc'],
    test_suite='test',
    entry_points={
        'console_scripts': ['cryptrality = cryptrality.commands:main']
    },
    install_requires=install_requires,
    classifiers=list(list_lines(classifier_text)),
    keywords='trading'
)
