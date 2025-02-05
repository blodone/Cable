
import sys
import random
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                           QHBoxLayout, QListWidget, QPushButton, QLabel,
                           QGraphicsView, QGraphicsScene, QGraphicsLineItem, QListWidgetItem,
                           QGraphicsPathItem, QCheckBox, QMenu, QAction, QSpacerItem, QSizePolicy)
from PyQt5.QtCore import Qt, QMimeData, QLineF, QPointF, QRectF, QTimer
from PyQt5.QtGui import (QDrag, QColor, QPainter, QBrush, QPalette, QPen,
                        QPainterPath)
import jack

class DragListWidget(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setDragDropMode(QListWidget.DragOnly)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

    def startDrag(self, supportedActions):
        item = self.currentItem()
        if item:
            mime_data = QMimeData()
            mime_data.setText(item.text())
            drag = QDrag(self)
            drag.setMimeData(mime_data)
            drag.exec_(Qt.CopyAction)

    def show_context_menu(self, position):
        item = self.itemAt(position)
        if item:
            menu = QMenu(self)
            disconnect_action = QAction("Disconnect", self)
            # Pass the item's text (port name) instead of the item itself
            disconnect_action.triggered.connect(lambda checked, name=item.text(): self.window().disconnect_node(name))
            menu.addAction(disconnect_action)
            menu.exec_(self.mapToGlobal(position))

class DropListWidget(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

    def dragEnterEvent(self, event):
        if event.mimeData().hasText():
            event.acceptProposedAction()

    def dropEvent(self, event):
        source = event.source()
        if isinstance(source, DragListWidget):
            output_name = event.mimeData().text()
            input_item = self.itemAt(event.pos())
            if input_item:
                input_name = input_item.text()
                self.window().make_connection(output_name, input_name)
        event.acceptProposedAction()

    def show_context_menu(self, position):
        item = self.itemAt(position)
        if item:
            menu = QMenu(self)
            disconnect_action = QAction("Disconnect", self)
            # Pass the item's text (port name) instead of the item itself
            disconnect_action.triggered.connect(lambda checked, name=item.text(): self.window().disconnect_node(name))
            menu.addAction(disconnect_action)
            menu.exec_(self.mapToGlobal(position))

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
        self.history = []  # List of (action, output_name, input_name) tuples
        self.current_index = -1

    def add_action(self, action, output_name, input_name):
        # Remove any future history when a new action is added
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
            # Return the opposite action needed to undo
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
        self.setGeometry(100, 100, 1500, 705)

        # Initialize JACK client
        self.client = jack.Client('ConnectionManager')
        self.connections = set()
        self.connection_colors = {}

        # Initialize connection history
        self.connection_history = ConnectionHistory()

        # Set up dark mode colors
        self.dark_mode = self.is_dark_mode()
        self.setup_colors()

        # Create main widget and layout
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QHBoxLayout(main_widget)

        # Create lists for inputs and outputs
        input_layout = QVBoxLayout()
        output_layout = QVBoxLayout()

        # Input section
        input_label = QLabel('Input Ports')
        input_label.setStyleSheet(f"color: {self.text_color.name()};")
        self.input_list = DropListWidget()
        self.input_list.itemClicked.connect(self.on_input_clicked)
        self.input_list.setStyleSheet(f"""
            QListWidget {{ background-color: {self.background_color.name()}; color: {self.text_color.name()}; }}
            QListWidget::item:selected {{ background-color: {self.highlight_color.name()}; color: {self.text_color.name()}; }}
        """)

        spacer = QSpacerItem(20, 34, QSizePolicy.Minimum, QSizePolicy.Fixed)
        input_layout.addSpacerItem(spacer)


        input_layout.addWidget(input_label)
        input_layout.addWidget(self.input_list)

        # Output section
        output_label = QLabel('Output Ports')
        output_label.setStyleSheet(f"color: {self.text_color.name()};")
        self.output_list = DragListWidget()
        self.output_list.itemClicked.connect(self.on_output_clicked)
        self.output_list.setStyleSheet(f"""
            QListWidget {{ background-color: {self.background_color.name()}; color: {self.text_color.name()}; }}
            QListWidget::item:selected {{ background-color: {self.highlight_color.name()}; color: {self.text_color.name()}; }}
        """)

        # Middle panel with controls and visualization
        middle_layout = QVBoxLayout()

        # Connection controls (button_layout)
        button_layout = QHBoxLayout()
        self.connect_button = QPushButton('Connect')
        self.disconnect_button = QPushButton('Disconnect')
        self.refresh_button = QPushButton('Refresh')
        self.auto_refresh_checkbox = QCheckBox('Auto Refresh')
        self.auto_refresh_checkbox.setChecked(True)
        for button in [self.connect_button, self.disconnect_button, self.refresh_button]:
            button.setStyleSheet(f"""
                QPushButton {{ background-color: {self.button_color.name()}; color: {self.text_color.name()}; }}
                QPushButton:hover {{ background-color: {self.highlight_color.name()}; }}
            """)
        button_layout.addWidget(self.connect_button)
        button_layout.addWidget(self.disconnect_button)
        button_layout.addWidget(self.refresh_button)
        button_layout.addWidget(self.auto_refresh_checkbox)

        # Add undo/redo buttons to button layout
        self.undo_button = QPushButton('Undo')
        self.redo_button = QPushButton('Redo')
        for button in [self.undo_button, self.redo_button]:
            button.setStyleSheet(f"""
                QPushButton {{ background-color: {self.button_color.name()}; color: {self.text_color.name()}; }}
                QPushButton:hover {{ background-color: {self.highlight_color.name()}; }}
            """)
            button.setEnabled(False)

        button_layout.addWidget(self.undo_button)
        button_layout.addWidget(self.redo_button)

        # Connect undo/redo buttons
        self.undo_button.clicked.connect(self.undo_action)
        self.redo_button.clicked.connect(self.redo_action)

        # Connection visualization
        self.connection_scene = QGraphicsScene()
        self.connection_view = ConnectionView(self.connection_scene)
        self.connection_view.setStyleSheet(f"background: {self.background_color.name()}; border: none;")

        # Add button_layout above the output_layout
        output_layout.addLayout(button_layout)  # Move button_layout here
        output_layout.addWidget(output_label)
        output_layout.addWidget(self.output_list)

        middle_layout.addWidget(self.connection_view)

        layout.addLayout(output_layout, 2)
        layout.addLayout(middle_layout, 1)
        layout.addLayout(input_layout, 2)

        self.connect_button.clicked.connect(self.make_connection_selected)
        self.disconnect_button.clicked.connect(self.break_connection_selected)
        self.refresh_button.clicked.connect(self.refresh_ports)
        self.auto_refresh_checkbox.stateChanged.connect(self.toggle_auto_refresh)

        # Initialize and start the timer
        self.timer = QTimer()
        self.timer.timeout.connect(self.refresh_ports)
        self.toggle_auto_refresh(Qt.Checked if self.auto_refresh_checkbox.isChecked() else Qt.Unchecked)

        # Initial refresh
        self.refresh_ports()
        self.quick_refresh_startup()


        ###########
        ###########

    def toggle_auto_refresh(self, state):
        if state == Qt.Checked:
            self.timer.start(1000)
        else:
            self.timer.stop()

    def quick_refresh_startup(self):
        if not self.auto_refresh_checkbox.isChecked():
            self.refresh_ports()
            QTimer.singleShot(500, self.refresh_ports)
            QTimer.singleShot(1000, self.refresh_ports)

    def adjust_window_size(self):
        self.input_list.updateGeometry()
        self.output_list.updateGeometry()
        self.adjustSize()

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

    def toggle_auto_refresh(self, state):
        if state == Qt.Checked:
            self.timer.start(1000)
        else:
            self.timer.stop()

    def refresh_ports(self):
        # Store current selections
        selected_input = self.input_list.currentItem().text() if self.input_list.currentItem() else None
        selected_output = self.output_list.currentItem().text() if self.output_list.currentItem() else None

        # Clear lists
        self.input_list.clear()
        self.output_list.clear()

        # Get and sort input and output ports separately
        input_ports = []
        output_ports = []

        for port in self.client.get_ports():
            if port.is_input:
                input_ports.append(port.name)
            elif port.is_output:
                output_ports.append(port.name)

        # Sort the ports alphabetically, ignoring case
        input_ports.sort(key=str.casefold)
        output_ports.sort(key=str.casefold)

        # Add sorted ports and restore selections
        for i, input_port in enumerate(input_ports):
            item = QListWidgetItem(input_port)
            self.input_list.addItem(item)
            if input_port == selected_input:
                self.input_list.setCurrentRow(i)

        for i, output_port in enumerate(output_ports):
            item = QListWidgetItem(output_port)
            self.output_list.addItem(item)
            if output_port == selected_output:
                self.output_list.setCurrentRow(i)

        self.update_connections()

        # Restore highlights based on current selection
        if selected_input:
            for output_port in self.client.get_ports(is_output=True):
                if selected_input in [conn.name for conn in self.client.get_all_connections(output_port)]:
                    self.highlight_output(output_port.name, auto_highlight=True)
        elif selected_output:
            for input_port in self.client.get_all_connections(selected_output):
                self.highlight_input(input_port.name, auto_highlight=True)

    def make_connection(self, output_name, input_name):
        try:
            self.client.connect(output_name, input_name)
            self.connection_history.add_action('connect', output_name, input_name)
            self.update_undo_redo_buttons()
            self.update_connections()
            self.refresh_ports()
        except jack.JackError as e:
            print(f"Connection error: {e}")

    def break_connection(self, output_name, input_name):
        try:
            self.client.disconnect(output_name, input_name)
            self.connection_history.add_action('disconnect', output_name, input_name)
            self.update_undo_redo_buttons()
            self.update_connections()
            self.refresh_ports()
        except jack.JackError as e:
            print(f"Disconnection error: {e}")

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
            if item.text() == port_name:
                rect = list_widget.visualItemRect(item)
                if list_widget == self.output_list:
                    point = rect.topRight() + QPointF(0, rect.height() / 2)
                else:
                    point = rect.topLeft() + QPointF(0, rect.height() / 2)
                global_point = list_widget.mapToGlobal(point.toPoint())
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
        input_name = item.text()
        item.setBackground(QBrush(self.highlight_color))
        for output_port in self.client.get_ports(is_output=True):
            if input_name in [conn.name for conn in self.client.get_all_connections(output_port)]:
                self.highlight_output(output_port.name, auto_highlight=True)

    def on_output_clicked(self, item):
        self.clear_highlights()
        output_name = item.text()
        item.setBackground(QBrush(self.highlight_color))
        for input_port in self.client.get_all_connections(output_name):
            self.highlight_input(input_port.name, auto_highlight=True)

    def highlight_input(self, input_name, auto_highlight=False):
        for i in range(self.input_list.count()):
            item = self.input_list.item(i)
            if item.text() == input_name:
                item.setBackground(QBrush(self.auto_highlight_color if auto_highlight else self.highlight_color))
                break

    def highlight_output(self, output_name, auto_highlight=False):
        for i in range(self.output_list.count()):
            item = self.output_list.item(i)
            if item.text() == output_name:
                item.setBackground(QBrush(self.auto_highlight_color if auto_highlight else self.highlight_color))
                break

    def clear_highlights(self):
        for i in range(self.input_list.count()):
            self.input_list.item(i).setBackground(QBrush(self.background_color))
        for i in range(self.output_list.count()):
            self.output_list.item(i).setBackground(QBrush(self.background_color))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_connections()

def main():
    app = QApplication(sys.argv)
    window = JackConnectionManager()
    window.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
