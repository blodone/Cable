### Maintainer: Your Name <your.email@example.com>

pkgname=cable
pkgver=0.3.1
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

sha256sums=('7c3fa49e8c21d6ced509e7b664b3c108fbaf1261a6171b87a38bc759565277d9'
            'a77215c8231903bd0a902bf40a332396376d8b72b41600e49909906cdea5b118'
            '5c3fa8b496c1a4a1918a2bfa2420cfa3ceedc93307d566a55c8f0835f3b33442'
            'a2a9f1eda97881a621f1ae24bc5c5ca7f7e79055f3673055f5cc922fe220609f'
            '3a6030d103e2399a9987f95f39987411c69f336d1006f8029b6d250aedd9a5ae')





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
