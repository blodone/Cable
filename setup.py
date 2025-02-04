from setuptools import setup

setup(
    name='cable',
    version='0.2.4',
    py_modules=['Cable'],
    entry_points={
        'console_scripts': [
            'cable = Cable:main',
        ],
    },
)
