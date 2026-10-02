from setuptools import setup

package_name = 'cute_tapochek_gui'

setup(
    name=package_name,
    version='0.1.0',
    package_dir={'': 'src'},
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml', 'plugin.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='banana-killer',
    maintainer_email='sashagrachev2005@gmail.com',
    description='rqt plugin "Motion Studio" for cute_tapochek',
    license='MIT',
    entry_points={
        'console_scripts': [
            'motion_studio = cute_tapochek_gui.main:main',
        ],
    },
)
