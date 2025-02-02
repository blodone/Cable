### Maintainer: Your Name <your.email@example.com>

pkgname=cable
pkgver=0.2.2
pkgrel=1
pkgdesc="A PyQt5 application to dynamically modify Pipewire and Wireplumber settings"
arch=('any')
url="https://github.com/magillos/Cable"
license=('GPL-3.0')
depends=('python' 'python-pyqt5' 'python-jack-client')
makedepends=('python-setuptools')
source=(
  "Cable.py::https://raw.githubusercontent.com/magillos/Cable/master/Cable.py"
  "setup.py::https://raw.githubusercontent.com/magillos/Cable/master/setup.py"
  "jack-plug.svg::https://raw.githubusercontent.com/magillos/Cable/master/jack-plug.svg"
  "cable.desktop::https://raw.githubusercontent.com/magillos/Cable/master/cable.desktop"
  "connection-manager.py::https://raw.githubusercontent.com/magillos/Cable/master/connection-manager.py"
)

sha256sums=('341bd9fd70a98a7b1ca013786c5fe5f034f1a306c46b1c57c62cdfed41a0a223'
            '1aa0a87fff5360f05e491ba62c0962b684e53d6ee45a070bf0ec86432f6df8c4'
            '5c3fa8b496c1a4a1918a2bfa2420cfa3ceedc93307d566a55c8f0835f3b33442'
            'a2a9f1eda97881a621f1ae24bc5c5ca7f7e79055f3673055f5cc922fe220609f'
            'f7f6b07b5f0f1d9cf18eaeee56e6c05ee58fc72c2a56419281112165011afef3')


build() {
  cd "$srcdir"
  python setup.py build
}

package() {
  cd "$srcdir"
  python setup.py install --root="$pkgdir/" --optimize=1

  # Install the icon
  install -Dm644 "$srcdir/jack-plug.svg" "$pkgdir/usr/share/icons/jack-plug.svg"

  # Install the desktop entry
  install -Dm644 "$srcdir/cable.desktop" "$pkgdir/usr/share/applications/cable.desktop"

  # Create the /usr/share/cable directory if it doesn't exist
  install -d "$pkgdir/usr/share/cable"

  # Install connection-manager.py to /usr/share/cable
  install -D "$srcdir/connection-manager.py" "$pkgdir/usr/share/cable/connection-manager.py"
}
