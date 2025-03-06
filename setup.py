from setuptools import setup

setup(
    name='cable',
    version='0.5.1.1',
    py_modules=['Cable'],
    entry_points={
        'console_scripts': [
            'cable = Cable:main',
        ],
    },
)
