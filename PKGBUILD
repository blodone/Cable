### Maintainer: Your Name <your.email@example.com>

pkgname=cable
pkgver=0.3.2
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

sha256sums=('8a2188d7feda6a0cb01b2aa405400ac4bfe047b567220dd85c0a03012b0d124f'
            '2fdf668ad3b60eebb4d780eabe13b6c38def8daa49bf4097589a40e5e691212a'
            '5c3fa8b496c1a4a1918a2bfa2420cfa3ceedc93307d566a55c8f0835f3b33442'
            'a2a9f1eda97881a621f1ae24bc5c5ca7f7e79055f3673055f5cc922fe220609f'
            '7c8edc8bdd58b93794fa04853cb6e56001ec2febd6d995b5168c108655e6b429')


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
