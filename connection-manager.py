import sys
import random
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QListWidget, QPushButton, QLabel,
                             QGraphicsView, QGraphicsScene, QGraphicsLineItem, QListWidgetItem,
                             QGraphicsPathItem, QCheckBox, QMenu, QAction, QSizePolicy, QSpacerItem)
from PyQt5.QtCore import Qt, QMimeData, QLineF, QPointF, QRectF, QTimer, QSize, QRect
from PyQt5.QtGui import (QDrag, QColor, QPainter, QBrush, QPalette, QPen,
                         QPainterPath, QFontMetrics, QFont)
import jack

class ElidedListWidgetItem(QListWidgetItem):
    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.full_text = text
        self.setText(self.full_text)

    def elide_text(self, text, width):
        font_metrics = QFontMetrics(self.font())
        return font_metrics.elidedText(text, Qt.ElideRight, width)

class DragListWidget(QListWidget):  # Now also a DropListWidget
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)  # Accept drops
        self.setDragDropMode(QListWidget.DragDrop)  # Allow both drag and drop
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumWidth(100)
        self._width = 150

    def sizeHint(self):
        return QSize(self._width, self.sizeHintForRow(0) * self.count() + 2)

    def addItem(self, item_or_text):
        if isinstance(item_or_text, str):
            item = ElidedListWidgetItem(item_or_text)
        else:
            item = item_or_text
        super().addItem(item)

    def startDrag(self, supportedActions):
        item = self.currentItem()
        if item:
            mime_data = QMimeData()
            mime_data.setText(item.full_text if isinstance(item, ElidedListWidgetItem) else item.text())
            drag = QDrag(self)
            drag.setMimeData(mime_data)
            drag.exec_(Qt.CopyAction)

    def dragEnterEvent(self, event):  # Handle drag enter
        if event.mimeData().hasText():
            event.acceptProposedAction()

    def dropEvent(self, event):  # Handle drops *onto* the output list
        source = event.source()
        if isinstance(source, DropListWidget):  # Dropped from input to output
            input_name = event.mimeData().text()
            output_item = self.itemAt(event.pos())
            if output_item:
                output_name = output_item.full_text if isinstance(output_item, ElidedListWidgetItem) else output_item.text()
                self.window().make_connection(output_name, input_name)  # Correct order
            event.acceptProposedAction()


    def show_context_menu(self, position):
        item = self.itemAt(position)
        if item:
            menu = QMenu(self)
            disconnect_action = QAction("Disconnect", self)
            disconnect_action.triggered.connect(lambda checked, name=(item.full_text if isinstance(item, ElidedListWidgetItem) else item.text()): self.window().disconnect_node(name))
            menu.addAction(disconnect_action)
            menu.exec_(self.mapToGlobal(position))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_elided_text()

    def update_elided_text(self):
        for index in range(self.count()):
            item = self.item(index)
            if isinstance(item, ElidedListWidgetItem):
                item.setText(item.elide_text(item.full_text, self.viewport().width() - 10))

class DropListWidget(QListWidget):  # Now also a DragListWidget
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragEnabled(True) # Allow dragging *from* the input list
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QListWidget.DragDrop) # Allow both drag and drop
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumWidth(100)
        self._width = 150

    def sizeHint(self):
        return QSize(self._width, self.sizeHintForRow(0) * self.count() + 2)

    def addItem(self, item_or_text):
        if isinstance(item_or_text, str):
            item = ElidedListWidgetItem(item_or_text)
        else:
            item = item_or_text
        super().addItem(item)

    def dragEnterEvent(self, event):
        if event.mimeData().hasText():
            event.acceptProposedAction()

    def startDrag(self, supportedActions): # Needed for dragging *from* input
        item = self.currentItem()
        if item:
            mime_data = QMimeData()
            mime_data.setText(item.full_text if isinstance(item, ElidedListWidgetItem) else item.text())
            drag = QDrag(self)
            drag.setMimeData(mime_data)
            drag.exec_(Qt.CopyAction)


    def dropEvent(self, event):  # Handle drops *onto* the input list
        source = event.source()
        if isinstance(source, DragListWidget):   # Dropped from output to input
            output_name = event.mimeData().text()
            input_item = self.itemAt(event.pos())
            if input_item:
                input_name = input_item.full_text if isinstance(input_item, ElidedListWidgetItem) else input_item.text()
                self.window().make_connection(output_name, input_name) # Correct order
        event.acceptProposedAction()

    def show_context_menu(self, position):
        item = self.itemAt(position)
        if item:
            menu = QMenu(self)
            disconnect_action = QAction("Disconnect", self)
            disconnect_action.triggered.connect(lambda checked, name=(item.full_text if isinstance(item, ElidedListWidgetItem) else item.text()): self.window().disconnect_node(name))
            menu.addAction(disconnect_action)
            menu.exec_(self.mapToGlobal(position))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_elided_text()

    def update_elided_text(self):
        for index in range(self.count()):
            item = self.item(index)
            if isinstance(item, ElidedListWidgetItem):
                item.setText(item.elide_text(item.full_text, self.viewport().width() - 10))


class ConnectionView(QGraphicsView):
    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHint(QPainter.Antialiasing, True)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fitInView(self.scene().sceneRect(), Qt.KeepAspectRatio)

class ConnectionHistory:
    def __init__(self):
        self.history = []
        self.current_index = -1

    def add_action(self, action, output_name, input_name):
        self.history = self.history[:self.current_index + 1]
        self.history.append((action, output_name, input_name))
        self.current_index += 1

    def can_undo(self):
        return self.current_index >= 0

    def can_redo(self):
        return self.current_index < len(self.history) - 1

    def undo(self):
        if self.can_undo():
            action, output_name, input_name = self.history[self.current_index]
            self.current_index -= 1
            return ('connect' if action == 'disconnect' else 'disconnect', output_name, input_name)
        return None

    def redo(self):
        if self.can_redo():
            self.current_index += 1
            return self.history[self.current_index]
        return None

class JackConnectionManager(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Cables')
        self.setGeometry(100, 100, 1200, 705)
        self.initial_middle_width = 250

        self.client = jack.Client('ConnectionManager')
        self.connections = set()
        self.connection_colors = {}
        self.connection_history = ConnectionHistory()
        self.dark_mode = self.is_dark_mode()
        self.setup_colors()

        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)

        input_layout = QVBoxLayout()
        output_layout = QVBoxLayout()

        input_label = QLabel(' Input Ports')
        font = QFont()
        font.setBold(True)
        input_label.setFont(font)
        input_label.setStyleSheet(f"color: {self.text_color.name()};")
        self.input_list = DropListWidget()  # Use the modified DropListWidget
        self.input_list.itemClicked.connect(self.on_input_clicked)
        self.input_list.setStyleSheet(f"""
            QListWidget {{ background-color: {self.background_color.name()}; color: {self.text_color.name()}; }}
            QListWidget::item:selected {{ background-color: {self.highlight_color.name()}; color: {self.text_color.name()}; }}
        """)

        spacer = QSpacerItem(20, 34, QSizePolicy.Minimum, QSizePolicy.Fixed)
        input_layout.addSpacerItem(spacer)

        input_layout.addWidget(input_label)
        input_layout.addWidget(self.input_list)

        output_label = QLabel(' Output Ports')
        output_label.setFont(font)
        output_label.setStyleSheet(f"color: {self.text_color.name()};")

        self.output_list = DragListWidget()  # Use the modified DragListWidget
        self.output_list.itemClicked.connect(self.on_output_clicked)
        self.output_list.setStyleSheet(f"""
            QListWidget {{ background-color: {self.background_color.name()}; color: {self.text_color.name()}; }}
            QListWidget::item:selected {{ background-color: {self.highlight_color.name()}; color: {self.text_color.name()}; }}
        """)

        spacer = QSpacerItem(20, 34, QSizePolicy.Minimum, QSizePolicy.Fixed)
        output_layout.addSpacerItem(spacer)

        output_layout.addWidget(output_label)
        output_layout.addWidget(self.output_list)

        middle_layout = QVBoxLayout()

        button_layout = QHBoxLayout()
        self.connect_button = QPushButton('Connect')
        self.disconnect_button = QPushButton('Disconnect')
        self.refresh_button = QPushButton('Refresh')
        for button in [self.connect_button, self.disconnect_button, self.refresh_button]:
            button.setStyleSheet(f"""
                QPushButton {{ background-color: {self.button_color.name()}; color: {self.text_color.name()}; }}
                QPushButton:hover {{ background-color: {self.highlight_color.name()}; }}
            """)
        button_layout.addWidget(self.connect_button)
        button_layout.addWidget(self.disconnect_button)
        button_layout.addWidget(self.refresh_button)

        self.connection_scene = QGraphicsScene()
        self.connection_view = ConnectionView(self.connection_scene)
        self.connection_view.setStyleSheet(f"background: {self.background_color.name()}; border: none;")

        middle_layout_widget = QWidget()
        middle_layout_widget.setLayout(middle_layout)
        middle_layout_widget.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        middle_layout_widget.setFixedWidth(self.initial_middle_width)


        middle_layout.addLayout(button_layout)
        middle_layout.addWidget(self.connection_view)

        bottom_layout = QHBoxLayout()
        self.auto_refresh_checkbox = QCheckBox('Auto Refresh')
        self.auto_refresh_checkbox.setChecked(True)
        self.undo_button = QPushButton('Undo')
        self.redo_button = QPushButton('Redo')

        button_size = self.connect_button.sizeHint()
        self.undo_button.setFixedSize(button_size)
        self.redo_button.setFixedSize(button_size)

        for button in [self.undo_button, self.redo_button]:
            button.setStyleSheet(f"""
                QPushButton {{ background-color: {self.button_color.name()}; color: {self.text_color.name()}; }}
                QPushButton:hover {{ background-color: {self.highlight_color.name()}; }}
            """)
            button.setEnabled(False)

        bottom_layout.addStretch()
        bottom_layout.addWidget(self.auto_refresh_checkbox)
        bottom_layout.addWidget(self.undo_button)
        bottom_layout.addWidget(self.redo_button)
        bottom_layout.addStretch()

        content_layout = QHBoxLayout()
        content_layout.addLayout(output_layout)
        content_layout.addWidget(middle_layout_widget)
        content_layout.addLayout(input_layout)

        layout.addLayout(content_layout)
        layout.addLayout(bottom_layout)

        self.connect_button.clicked.connect(self.make_connection_selected)
        self.disconnect_button.clicked.connect(self.break_connection_selected)
        self.refresh_button.clicked.connect(self.refresh_ports)
        self.auto_refresh_checkbox.stateChanged.connect(self.toggle_auto_refresh)
        self.undo_button.clicked.connect(self.undo_action)
        self.redo_button.clicked.connect(self.redo_action)

        self.timer = QTimer()
        self.timer.timeout.connect(self.refresh_ports)
        self.toggle_auto_refresh(Qt.Checked if self.auto_refresh_checkbox.isChecked() else Qt.Unchecked)

        self.refresh_ports()
        self.update_disconnect_button()

    def toggle_auto_refresh(self, state):
        if state == Qt.Checked:
            self.timer.start(1000)
        else:
            self.timer.stop()

    def is_dark_mode(self):
        palette = QApplication.palette()
        return palette.window().color().lightness() < 128

    def setup_colors(self):
        if self.dark_mode:
            self.background_color = QColor(53, 53, 53)
            self.text_color = QColor(255, 255, 255)
            self.highlight_color = QColor(42, 130, 218)
            self.button_color = QColor(68, 68, 68)
            self.connection_color = QColor(0, 150, 255)
            self.auto_highlight_color = QColor(255, 165, 0)
        else:
            self.background_color = QColor(255, 255, 255)
            self.text_color = QColor(0, 0, 0)
            self.highlight_color = QColor(173, 216, 230)
            self.button_color = QColor(240, 240, 240)
            self.connection_color = QColor(0, 100, 200)
            self.auto_highlight_color = QColor(255, 140, 0)

    def refresh_ports(self):
        current_input_text = self.input_list.currentItem().text() if self.input_list.currentItem() else None
        current_output_text = self.output_list.currentItem().text() if self.output_list.currentItem() else None

        self.input_list.clear()
        self.output_list.clear()

        input_ports = []
        output_ports = []

        for port in self.client.get_ports():
            if port.is_input:
                input_ports.append(port.name)
            elif port.is_output:
                output_ports.append(port.name)

        input_ports.sort(key=str.casefold)
        output_ports.sort(key=str.casefold)

        for i, input_port in enumerate(input_ports):
            item = QListWidgetItem(input_port)
            self.input_list.addItem(item)
            if current_input_text and item.text() == current_input_text:
               self.input_list.setCurrentItem(item)

        for i, output_port in enumerate(output_ports):
            item = QListWidgetItem(output_port)
            self.output_list.addItem(item)
            if current_output_text and item.text() == current_output_text:
                self.output_list.setCurrentItem(item)


        self.input_list.update_elided_text()
        self.output_list.update_elided_text()

        self.update_connections()
        self.clear_highlights()


        if current_input_text:
            for output_port in self.client.get_ports(is_output=True):
                if current_input_text in [conn.name for conn in self.client.get_all_connections(output_port)]:
                    self.highlight_output(output_port.name, auto_highlight=True)
        if current_output_text:
            for input_port in self.client.get_all_connections(current_output_text):
                self.highlight_input(input_port.name, auto_highlight=True)

        self.update_disconnect_button()



    def make_connection(self, output_name, input_name):
        try:
            self.client.connect(output_name, input_name)
            self.connection_history.add_action('connect', output_name, input_name)
            self.update_undo_redo_buttons()
            self.update_connections()
            self.refresh_ports()
        except jack.JackError as e:
            print(f"Connection error: {e}")

        self.update_disconnect_button()


    def break_connection(self, output_name, input_name):
        try:
            self.client.disconnect(output_name, input_name)
            self.connection_history.add_action('disconnect', output_name, input_name)
            self.update_undo_redo_buttons()
            self.update_connections()
            self.refresh_ports()
        except jack.JackError as e:
            print(f"Disconnection error: {e}")

        self.update_disconnect_button()


    def update_undo_redo_buttons(self):
        self.undo_button.setEnabled(self.connection_history.can_undo())
        self.redo_button.setEnabled(self.connection_history.can_redo())

    def undo_action(self):
        action = self.connection_history.undo()
        if action:
            action_type, output_name, input_name = action
            try:
                if action_type == 'connect':
                    self.client.connect(output_name, input_name)
                else:
                    self.client.disconnect(output_name, input_name)
                self.update_undo_redo_buttons()
                self.update_connections()
                self.refresh_ports()
            except jack.JackError as e:
                print(f"Undo error: {e}")
            self.update_disconnect_button()


    def redo_action(self):
        action = self.connection_history.redo()
        if action:
            action_type, output_name, input_name = action
            try:
                if action_type == 'connect':
                    self.client.connect(output_name, input_name)
                else:
                    self.client.disconnect(output_name, input_name)
                self.update_undo_redo_buttons()
                self.update_connections()
                self.refresh_ports()
            except jack.JackError as e:
                print(f"Redo error: {e}")
            self.update_disconnect_button()


    def disconnect_node(self, node_name):
        if node_name in [port.name for port in self.client.get_ports(is_input=True)]:
            for output_port in self.client.get_ports(is_output=True):
                if node_name in [conn.name for conn in self.client.get_all_connections(output_port)]:
                    self.break_connection(output_port.name, node_name)
        elif node_name in [port.name for port in self.client.get_ports(is_output=True)]:
            for input_port in self.client.get_all_connections(node_name):
                self.break_connection(node_name, input_port.name)

    def make_connection_selected(self):
        input_item = self.input_list.currentItem()
        output_item = self.output_list.currentItem()
        if input_item and output_item:
            self.make_connection(output_item.text(), input_item.text())

    def break_connection_selected(self):
        input_item = self.input_list.currentItem()
        output_item = self.output_list.currentItem()
        if input_item and output_item:
            self.break_connection(output_item.text(), input_item.text())

    def get_port_position(self, list_widget, port_name):
        for i in range(list_widget.count()):
            item = list_widget.item(i)
            if item.text() == port_name or (isinstance(item, ElidedListWidgetItem) and item.full_text == port_name):
                rect = list_widget.visualItemRect(item)
                if list_widget == self.output_list:
                    point = QPointF(list_widget.viewport().width(), rect.top() + rect.height() / 2)
                else:
                    point = rect.topLeft() + QPointF(0, rect.height() / 2)

                viewport_point = list_widget.viewport().mapToParent(point.toPoint())
                global_point = list_widget.mapToGlobal(viewport_point)
                scene_point = self.connection_view.mapFromGlobal(global_point)
                return self.connection_view.mapToScene(scene_point)

        return None

    def get_random_color(self, base_name):
        random.seed(base_name)
        return QColor(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))

    def update_connections(self):
        self.connection_scene.clear()
        view_rect = self.connection_view.rect()
        scene_rect = QRectF(0, 0, view_rect.width(), view_rect.height())
        self.connection_scene.setSceneRect(scene_rect)

        connections = []
        for output_port in self.client.get_ports(is_output=True):
            for input_port in self.client.get_all_connections(output_port):
                connections.append((output_port.name, input_port.name))

        for output_name, input_name in connections:
            start_pos = self.get_port_position(self.output_list, output_name)
            end_pos = self.get_port_position(self.input_list, input_name)
            if start_pos and end_pos:
                path = QPainterPath()
                path.moveTo(start_pos)
                ctrl1_x = start_pos.x() + (end_pos.x() - start_pos.x()) / 3
                ctrl2_x = start_pos.x() + 2 * (end_pos.x() - start_pos.x()) / 3
                path.cubicTo(
                    QPointF(ctrl1_x, start_pos.y()),
                    QPointF(ctrl2_x, end_pos.y()),
                    end_pos
                )
                base_name = output_name.rsplit(':', 1)[0]
                color = self.get_random_color(base_name)
                pen = QPen(color, 2)
                path_item = QGraphicsPathItem(path)
                path_item.setPen(pen)
                self.connection_scene.addItem(path_item)

        self.connection_view.fitInView(self.connection_scene.sceneRect(), Qt.KeepAspectRatio)

    def on_input_clicked(self, item):
        self.clear_highlights()
        self.input_list.setCurrentItem(item)
        input_name = item.text()

        self.highlight_input(input_name)

        for output_port in self.client.get_ports(is_output=True):
            if input_name in [conn.name for conn in self.client.get_all_connections(output_port)]:
                self.highlight_output(output_port.name, auto_highlight=True)

        self.update_disconnect_button()


    def on_output_clicked(self, item):
        self.clear_highlights()
        self.output_list.setCurrentItem(item)
        output_name = item.text()

        self.highlight_output(output_name)

        for input_port in self.client.get_all_connections(output_name):
            self.highlight_input(input_port.name, auto_highlight=True)

        self.update_disconnect_button()


    def highlight_input(self, input_name, auto_highlight=False):
        for i in range(self.input_list.count()):
            item = self.input_list.item(i)
            if (isinstance(item, ElidedListWidgetItem) and item.full_text == input_name) or item.text() == input_name:
                item.setBackground(QBrush(self.highlight_color if not auto_highlight else self.auto_highlight_color))
                break

    def highlight_output(self, output_name, auto_highlight=False):
        for i in range(self.output_list.count()):
            item = self.output_list.item(i)
            if (isinstance(item, ElidedListWidgetItem) and item.full_text == output_name) or item.text() == output_name:
                item.setBackground(QBrush(self.highlight_color if not auto_highlight else self.auto_highlight_color))
                break

    def clear_highlights(self):
        for i in range(self.input_list.count()):
            self.input_list.item(i).setBackground(QBrush(self.background_color))
        for i in range(self.output_list.count()):
            self.output_list.item(i).setBackground(QBrush(self.background_color))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_connections()
        self.input_list.update_elided_text()
        self.output_list.update_elided_text()

    def update_disconnect_button(self):
        input_item = self.input_list.currentItem()
        output_item = self.output_list.currentItem()

        if input_item and output_item:
            output_name = output_item.text()
            input_name = input_item.text()
            connected = False
            for input_port in self.client.get_all_connections(output_name):
                if input_port.name == input_name:
                    connected = True
                    break
            self.disconnect_button.setEnabled(connected)
        else:
            self.disconnect_button.setEnabled(False)


def main():
    app = QApplication(sys.argv)
    window = JackConnectionManager()
    window.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
