from setuptools import setup

setup(
    name='cable',
    version='0.9.3.1',
    py_modules=['Cable'],
    entry_points={
        'console_scripts': [
            'cable = Cable:main',
        ],
    },
)
