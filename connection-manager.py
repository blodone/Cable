import sys
import random
import re
import configparser
import os
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QListWidget, QPushButton, QLabel,
                             QGraphicsView, QGraphicsScene, QTabWidget, QListWidgetItem,
                             QGraphicsPathItem, QCheckBox, QMenu, QAction, QSizePolicy, QSpacerItem,
                             QButtonGroup)
from PyQt5.QtCore import Qt, QMimeData, QPointF, QRectF, QTimer, QSize, QRect
from PyQt5.QtGui import (QDrag, QColor, QPainter, QBrush, QPalette, QPen,
                         QPainterPath, QFontMetrics, QFont)
import jack

class ConfigManager:
    def __init__(self):
        self.config = configparser.ConfigParser()
        self.config_dir = os.path.expanduser('~/.config/cable')
        self.config_file = os.path.join(self.config_dir, 'config.ini')
        self.load_config()

    def load_config(self):
        # Create directory if it doesn't exist
        if not os.path.exists(self.config_dir):
            os.makedirs(self.config_dir)

        # Load existing config or create with defaults
        if os.path.exists(self.config_file):
            self.config.read(self.config_file)

        # Ensure DEFAULT section exists
        if 'DEFAULT' not in self.config:
            self.config['DEFAULT'] = {}

        # Set defaults if not present
        defaults = {
            'tray_enabled': 'True',
            'tray_click_opens_cables': 'True',
            'auto_refresh_enabled': 'True'  # Add default for auto refresh
        }

        for key, value in defaults.items():
            if key not in self.config['DEFAULT']:
                self.config['DEFAULT'][key] = value

        self.save_config()

    def save_config(self):
        with open(self.config_file, 'w') as configfile:
            self.config.write(configfile)

    def get_bool(self, key, default=True):
        return self.config['DEFAULT'].getboolean(key, default)

    def set_bool(self, key, value):
        self.config['DEFAULT'][key] = str(value)
        self.save_config()


class ElidedListWidgetItem(QListWidgetItem):
    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.full_text = text
        self.setText(self.full_text)

    def elide_text(self, text, width):
        font_metrics = QFontMetrics(self.font())
        return font_metrics.elidedText(text, Qt.ElideRight, width)

class PortListWidget(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumWidth(100)
        self._width = 150
        self.current_drag_highlight_item = None

    def sizeHint(self):
        return QSize(self._width, self.sizeHintForRow(0) * self.count() + 2)

    def addItem(self, item_or_text):
        if isinstance(item_or_text, str):
            item = ElidedListWidgetItem(item_or_text)
        else:
            item = item_or_text
        super().addItem(item)

    def show_context_menu(self, position):
        item = self.itemAt(position)
        if item:
            menu = QMenu(self)
            disconnect_action = QAction("Disconnect all", self)
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

    def dragLeaveEvent(self, event):
        self.window().clear_drop_target_highlight(self)
        self.current_drag_highlight_item = None
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self.window().clear_drop_target_highlight(self)
        self.current_drag_highlight_item = None
        super().dropEvent(event)


class DragListWidget(PortListWidget): # Output List
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True) # Accept drops
        self.setDragDropMode(QListWidget.DragDrop)


    def startDrag(self, supportedActions):
        item = self.currentItem()
        if item:
            mime_data = QMimeData()
            mime_data.setText(item.full_text if isinstance(item, ElidedListWidgetItem) else item.text())
            drag = QDrag(self)
            drag.setMimeData(mime_data)
            drag.exec_(Qt.CopyAction)

    def dragEnterEvent(self, event):  # Handle drag enter for drops *onto* output list
        if event.mimeData().hasText():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        item = self.itemAt(event.pos())
        if item and item != self.current_drag_highlight_item:
            self.window().clear_drop_target_highlight(self)
            self.window().highlight_drop_target_item(self, item)
            self.current_drag_highlight_item = item
        elif not item:
            self.window().clear_drop_target_highlight(self)
            self.current_drag_highlight_item = None
        super().dragMoveEvent(event)


    def dropEvent(self, event):  # Handle drops *onto* the output list
        source = event.source()
        if isinstance(source, DropListWidget):  # Dropped from input to output
            input_name = event.mimeData().text() # Get input name from mime data
            output_item = self.itemAt(event.pos()) # Get output item at drop position
            if output_item:
                output_name = output_item.full_text if isinstance(output_item, ElidedListWidgetItem) else output_item.text() # Get output name
                self.window().make_connection(output_name, input_name)  # Correct order: output -> input
            event.acceptProposedAction()
        super().dropEvent(event)


class DropListWidget(PortListWidget): # Input List
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QListWidget.DragDrop)


    def dragEnterEvent(self, event): # for drag *from* input list - not needed for drops *onto* input list in this direction
        if event.mimeData().hasText():
            event.acceptProposedAction()

    def startDrag(self, supportedActions): # for drag *from* input list
        item = self.currentItem()
        if item:
            mime_data = QMimeData()
            mime_data.setText(item.full_text if isinstance(item, ElidedListWidgetItem) else item.text())
            drag = QDrag(self)
            drag.setMimeData(mime_data)
            drag.exec_(Qt.CopyAction)

    def dragMoveEvent(self, event):
        item = self.itemAt(event.pos())
        if item and item != self.current_drag_highlight_item:
            self.window().clear_drop_target_highlight(self)
            self.window().highlight_drop_target_item(self, item)
            self.current_drag_highlight_item = item
        elif not item:
            self.window().clear_drop_target_highlight(self)
            self.current_drag_highlight_item = None
        super().dragMoveEvent(event)


    def dropEvent(self, event):  # Handle drops *onto* the input list (from output list)
        source = event.source()
        if isinstance(source, DragListWidget):   # Ensure the source is the output list
            output_name = event.mimeData().text() # Get the dragged output port name
            input_item = self.itemAt(event.pos()) # Get the input item where it's dropped
            if input_item:
                input_name = input_item.full_text if isinstance(input_item, ElidedListWidgetItem) else input_item.text() # Get the input port name
                self.window().make_connection(output_name, input_name) # Make the connection: output -> input
            event.acceptProposedAction()
        else:
            event.ignore() # If the source is not DragListWidget, ignore the drop
        super().dropEvent(event)


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
        self.config_manager = ConfigManager()
        self.minimize_on_close = True
        self.setWindowTitle('Cables')
        self.setGeometry(100, 100, 1250, 705)
        self.initial_middle_width = 250
        self.port_type = 'audio'
        self.client = jack.Client('ConnectionManager')
        self.connections = set()
        self.connection_colors = {}
        self.connection_history = ConnectionHistory()
        self.dark_mode = self.is_dark_mode()
        self.setup_colors()

        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)

        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)

        self.audio_tab_widget = QWidget()
        self.midi_tab_widget = QWidget()

        self.setup_port_tab(self.audio_tab_widget, "Audio", 'audio')
        self.setup_port_tab(self.midi_tab_widget, "MIDI", 'midi')

        self.tab_widget.addTab(self.audio_tab_widget, "Audio")
        self.tab_widget.addTab(self.midi_tab_widget, "MIDI")
        self.tab_widget.currentChanged.connect(self.switch_tab)

        self.setup_bottom_layout(main_layout)

        # Initialize the startup refresh timer
        self.startup_refresh_timer = QTimer()
        self.startup_refresh_timer.timeout.connect(self.startup_refresh)
        self.startup_refresh_count = 0

        # Initial refresh will happen after showing the window
        QTimer.singleShot(10, self.start_startup_refresh)

    def start_startup_refresh(self):
        """Start the rapid refresh sequence on startup"""
        self.startup_refresh_count = 0
        self.startup_refresh_timer.start(10)  # 10ms interval

    def startup_refresh(self):
        """Handle the rapid refresh sequence"""
        self.refresh_ports()
        self.startup_refresh_count += 1

        if self.startup_refresh_count >= 3:
            self.startup_refresh_timer.stop()
            # After quick refresh burst, start normal auto-refresh if enabled
            if self.auto_refresh_checkbox.isChecked():
                self.timer.start(1000)

    def setup_port_tab(self, tab_widget, tab_name, port_type):
        layout = QVBoxLayout(tab_widget)

        input_layout = QVBoxLayout()
        output_layout = QVBoxLayout()

        input_label = QLabel(f' {tab_name} Input Ports')
        output_label = QLabel(f' {tab_name} Output Ports')

        font = QFont()
        font.setBold(True)
        input_label.setFont(font)
        output_label.setFont(font)
        input_label.setStyleSheet(f"color: {self.text_color.name()};")
        output_label.setStyleSheet(f"color: {self.text_color.name()};")

        input_list = DropListWidget()
        output_list = DragListWidget()
        connection_scene = QGraphicsScene()
        connection_view = ConnectionView(connection_scene)

        input_list.setStyleSheet(self.list_stylesheet())
        output_list.setStyleSheet(self.list_stylesheet())
        connection_view.setStyleSheet(f"background: {self.background_color.name()}; border: none;")

        input_layout.addSpacerItem(QSpacerItem(20, 17, QSizePolicy.Minimum, QSizePolicy.Fixed))
        output_layout.addSpacerItem(QSpacerItem(20, 17, QSizePolicy.Minimum, QSizePolicy.Fixed))

        input_layout.addWidget(input_label)
        input_layout.addWidget(input_list)
        output_layout.addWidget(output_label)
        output_layout.addWidget(output_list)

        middle_layout = QVBoxLayout()
        button_layout = QHBoxLayout()
        connect_button = QPushButton('Connect')
        disconnect_button = QPushButton('Disconnect')
        refresh_button = QPushButton('Refresh')

        for button in [connect_button, disconnect_button, refresh_button]:
            button.setStyleSheet(self.button_stylesheet())

        button_layout.addWidget(connect_button)
        button_layout.addWidget(disconnect_button)
        button_layout.addWidget(refresh_button)

        middle_layout_widget = QWidget()
        middle_layout_widget.setLayout(middle_layout)
        middle_layout_widget.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        middle_layout_widget.setFixedWidth(self.initial_middle_width)

        middle_layout.addLayout(button_layout)
        middle_layout.addWidget(connection_view)

        content_layout = QHBoxLayout()
        content_layout.addLayout(output_layout)
        content_layout.addWidget(middle_layout_widget)
        content_layout.addLayout(input_layout)
        layout.addLayout(content_layout)

        if port_type == 'audio':
            self.input_list = input_list
            self.output_list = output_list
            self.connection_scene = connection_scene
            self.connection_view = connection_view
            self.connect_button = connect_button
            self.disconnect_button = disconnect_button
            self.refresh_button = refresh_button
            input_list.itemClicked.connect(self.on_input_clicked)
            output_list.itemClicked.connect(self.on_output_clicked)
            connect_button.clicked.connect(self.make_connection_selected)
            disconnect_button.clicked.connect(self.break_connection_selected)
            refresh_button.clicked.connect(self.refresh_ports)
        elif port_type == 'midi':
            self.midi_input_list = input_list
            self.midi_output_list = output_list
            self.midi_connection_scene = connection_scene
            self.midi_connection_view = connection_view
            self.midi_connect_button = connect_button
            self.midi_disconnect_button = disconnect_button
            input_list.itemClicked.connect(self.on_midi_input_clicked)
            output_list.itemClicked.connect(self.on_midi_output_clicked)
            connect_button.clicked.connect(self.make_midi_connection_selected)
            disconnect_button.clicked.connect(self.break_midi_connection_selected)
            refresh_button.clicked.connect(self.refresh_ports)


    def setup_bottom_layout(self, main_layout):
        bottom_layout = QHBoxLayout()
        self.auto_refresh_checkbox = QCheckBox('Auto Refresh')

        # Load auto refresh state from config
        auto_refresh_enabled = self.config_manager.get_bool('auto_refresh_enabled', True)
        self.auto_refresh_checkbox.setChecked(auto_refresh_enabled)

        self.undo_button = QPushButton('Undo')
        self.redo_button = QPushButton('Redo')

        button_size = self.connect_button.sizeHint()
        self.undo_button.setFixedSize(button_size)
        self.redo_button.setFixedSize(button_size)

        for button in [self.undo_button, self.redo_button]:
            button.setStyleSheet(self.button_stylesheet())
            button.setEnabled(False)

        bottom_layout.addStretch()
        bottom_layout.addWidget(self.auto_refresh_checkbox)
        bottom_layout.addWidget(self.undo_button)
        bottom_layout.addWidget(self.redo_button)
        bottom_layout.addStretch()
        main_layout.addLayout(bottom_layout)

        self.auto_refresh_checkbox.stateChanged.connect(self.toggle_auto_refresh)
        self.undo_button.clicked.connect(self.undo_action)
        self.redo_button.clicked.connect(self.redo_action)
        self.timer = QTimer()
        self.timer.timeout.connect(self.refresh_ports)
        # Don't start the normal timer yet - let the startup refresh handle it
        self.auto_refresh_enabled = auto_refresh_enabled


    def switch_tab(self, index):
        self.port_type = 'audio' if index == 0 else 'midi'
        self.refresh_ports()

    def toggle_auto_refresh(self, state):
        is_checked = state == Qt.Checked
        if is_checked:
            self.timer.start(1000)
        else:
            self.timer.stop()
        # Save state to config
        self.config_manager.set_bool('auto_refresh_enabled', is_checked)

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
            self.drag_highlight_color = QColor(100, 100, 100) # New color for drag highlight
        else:
            self.background_color = QColor(255, 255, 255)
            self.text_color = QColor(0, 0, 0)
            self.highlight_color = QColor(173, 216, 230)
            self.button_color = QColor(240, 240, 240)
            self.connection_color = QColor(0, 100, 200)
            self.auto_highlight_color = QColor(255, 140, 0)
            self.drag_highlight_color = QColor(200, 200, 200) # New color for drag highlight


    def list_stylesheet(self):
        return f"""
            QListWidget {{ background-color: {self.background_color.name()}; color: {self.text_color.name()}; }}
            QListWidget::item:selected {{ background-color: {self.highlight_color.name()}; color: {self.text_color.name()}; }}
        """

    def button_stylesheet(self):
        return f"""
            QPushButton {{ background-color: {self.button_color.name()}; color: {self.text_color.name()}; }}
            QPushButton:hover {{ background-color: {self.highlight_color.name()}; }}
        """

    def refresh_ports(self):
        if self.port_type == 'audio':
            current_input_text = self.input_list.currentItem().text() if self.input_list.currentItem() else None
            current_output_text = self.output_list.currentItem().text() if self.output_list.currentItem() else None

            self.input_list.clear()
            self.output_list.clear()
            input_ports, output_ports = self._get_ports(is_midi=False)

            for input_port in input_ports:
                item = QListWidgetItem(input_port)
                self.input_list.addItem(item)
                if current_input_text and item.text() == current_input_text:
                   self.input_list.setCurrentItem(item)

            for output_port in output_ports:
                item = QListWidgetItem(output_port)
                self.output_list.addItem(item)
                if current_output_text and item.text() == current_output_text:
                    self.output_list.setCurrentItem(item)

            self.input_list.update_elided_text()
            self.output_list.update_elided_text()
            self.update_connections()
            self.clear_highlights()
            self.update_connection_buttons() # Renamed and generalized
            self._highlight_connected_ports(current_input_text, current_output_text, is_midi=False)

        elif self.port_type == 'midi':
            current_input_text = self.midi_input_list.currentItem().text() if self.midi_input_list.currentItem() else None
            current_output_text = self.midi_output_list.currentItem().text() if self.midi_output_list.currentItem() else None

            self.midi_input_list.clear()
            self.midi_output_list.clear()
            input_ports, output_ports = self._get_ports(is_midi=True)

            for input_port in input_ports:
                self.midi_input_list.addItem(input_port)
            for output_port in output_ports:
                self.midi_output_list.addItem(output_port)

            if current_input_text:
                self._set_current_item_by_text(self.midi_input_list, current_input_text)
            if current_output_text:
                self._set_current_item_by_text(self.midi_output_list, current_output_text)

            self.midi_input_list.update_elided_text()
            self.midi_output_list.update_elided_text()
            self.update_midi_connections()
            self.clear_midi_highlights()
            self.update_midi_connection_buttons() # Renamed and generalized
            self._highlight_connected_ports(current_input_text, current_output_text, is_midi=True)


    def _set_current_item_by_text(self, list_widget, text):
        for i in range(list_widget.count()):
            if list_widget.item(i).text() == text:
                list_widget.setCurrentRow(i)
                break

    def _sort_ports(self, port_names):
        def get_sort_key(port_name):
            parts = re.split(r'(\d+)', port_name)
            key = []
            for part in parts:
                if part.isdigit():
                    key.append(int(part))
                else:
                    key.append(part.lower())
            return key

        return sorted(port_names, key=get_sort_key)


    def _get_ports(self, is_midi):
        input_ports = []
        output_ports = []
        for port in self.client.get_ports():
            if port.is_midi == is_midi:
                if port.is_input:
                    input_ports.append(port.name)
                elif port.is_output:
                    output_ports.append(port.name)

        input_ports = self._sort_ports(input_ports) # Apply custom sort
        output_ports = self._sort_ports(output_ports) # Apply custom sort
        return input_ports, output_ports

    def _highlight_connected_ports(self, current_input_text, current_output_text, is_midi):
        if current_input_text:
            output_ports = self.client.get_ports(is_output=True)
            for output_port in output_ports:
                if output_port.is_midi != is_midi:
                    continue
                if current_input_text in [c.name for c in self.client.get_all_connections(output_port)]:
                    if is_midi:
                        self.highlight_midi_output(output_port.name, auto_highlight=True)
                    else:
                        self.highlight_output(output_port.name, auto_highlight=True)
        if current_output_text:
            input_ports = [p for p in self.client.get_ports(is_input=True)]
            for input_port in input_ports:
                if input_port.is_midi != is_midi:
                    continue
                if current_output_text in [c.name for c in self.client.get_all_connections(input_port)]:
                    if is_midi:
                        self.highlight_midi_input(input_port.name, auto_highlight=True)
                    else:
                        self.highlight_input(input_port.name, auto_highlight=True)


    def make_connection(self, output_name, input_name):
        self._port_operation('connect', output_name, input_name, is_midi=False)

    def make_midi_connection(self, output_name, input_name):
        self._port_operation('connect', output_name, input_name, is_midi=True)

    def break_connection(self, output_name, input_name):
        self._port_operation('disconnect', output_name, input_name, is_midi=False)

    def break_midi_connection(self, output_name, input_name):
        self._port_operation('disconnect', output_name, input_name, is_midi=True)

    def _port_operation(self, operation_type, output_name, input_name, is_midi):
        try:
            if operation_type == 'connect':
                self.client.connect(output_name, input_name)
                self.connection_history.add_action('connect', output_name, input_name)
            else:
                self.client.disconnect(output_name, input_name)
                self.connection_history.add_action('disconnect', output_name, input_name)

            self.update_undo_redo_buttons()
            self.update_connections()
            self.refresh_ports()
            self.update_connection_buttons() # Updated here
            self.update_midi_connection_buttons() # Updated here


        except jack.JackError as e:
            print(f"{operation_type.capitalize()} error: {e}")


    def make_connection_selected(self):
        input_item = self.input_list.currentItem()
        output_item = self.output_list.currentItem()
        if input_item and output_item:
            self.make_connection(output_item.text(), input_item.text())

    def make_midi_connection_selected(self):
        input_item = self.midi_input_list.currentItem()
        output_item = self.midi_output_list.currentItem()
        if input_item and output_item:
            self.make_midi_connection(output_item.text(), input_item.text())

    def break_connection_selected(self):
        input_item = self.input_list.currentItem()
        output_item = self.output_list.currentItem()
        if input_item and output_item:
            self.break_connection(output_item.text(), input_item.text())

    def break_midi_connection_selected(self):
        input_item = self.midi_input_list.currentItem()
        output_item = self.midi_output_list.currentItem()
        if input_item and output_item:
            self.break_midi_connection(output_item.text(), input_item.text())

    def update_undo_redo_buttons(self):
        self.undo_button.setEnabled(self.connection_history.can_undo())
        self.redo_button.setEnabled(self.connection_history.can_redo())

    def undo_action(self):
        action = self.connection_history.undo()
        if action:
            action_type, output_name, input_name = action
            is_midi = 'midi' in output_name or 'midi' in input_name # heuristic to determine midi or audio
            try:
                if action_type == 'connect':
                    self.client.connect(output_name, input_name)
                else:
                    self.client.disconnect(output_name, input_name)
                self.update_undo_redo_buttons()
                self.update_connections()
                self.refresh_ports()
                self.update_connection_buttons() # Updated here
                self.update_midi_connection_buttons() # Updated here


            except jack.JackError as e:
                print(f"Undo error: {e}")


    def redo_action(self):
        action = self.connection_history.redo()
        if action:
            action_type, output_name, input_name = action
            is_midi = 'midi' in output_name or 'midi' in input_name # heuristic to determine midi or audio
            try:
                if action_type == 'connect':
                    self.client.connect(output_name, input_name)
                else:
                    self.client.disconnect(output_name, input_name)
                self.update_undo_redo_buttons()
                self.update_connections()
                self.refresh_ports()
                self.update_connection_buttons() # Updated here
                self.update_midi_connection_buttons() # Updated here
            except jack.JackError as e:
                print(f"Redo error: {e}")


    def disconnect_node(self, node_name):
        is_midi = 'midi' in node_name # heuristic to determine midi or audio
        ports = self.client.get_ports(is_input=True) if node_name in [port.name for port in self.client.get_ports(is_input=True)] else self.client.get_ports(is_output=True)

        if node_name in [port.name for port in self.client.get_ports(is_input=True)]:
            for output_port in self.client.get_ports(is_output=True):
                if node_name in [conn.name for conn in self.client.get_all_connections(output_port)]:
                    if not is_midi:
                        self.break_connection(output_port.name, node_name)
                    else:
                        self.break_midi_connection(output_port.name, node_name)
        elif node_name in [port.name for port in self.client.get_ports(is_output=True)]:
            for input_port in self.client.get_all_connections(node_name):
                    if not is_midi:
                        self.break_connection(node_name, input_port.name)
                    else:
                        self.break_midi_connection(node_name, input_port.name)


    def get_port_position(self, list_widget, port_name, connection_view):
        for i in range(list_widget.count()):
            item = list_widget.item(i)
            if (isinstance(item, ElidedListWidgetItem) and item.full_text == port_name) or item.text() == port_name:
                rect = list_widget.visualItemRect(item)
                point = QPointF(list_widget.viewport().width() if list_widget in (self.output_list, self.midi_output_list) else 0, rect.top() + rect.height() / 2)
                viewport_point = list_widget.viewport().mapToParent(point.toPoint())
                global_point = list_widget.mapToGlobal(viewport_point)
                scene_point = connection_view.mapFromGlobal(global_point)
                return connection_view.mapToScene(scene_point)
        return None

    def get_random_color(self, base_name):
        random.seed(base_name)
        return QColor(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))

    def update_connections(self):
        self._update_connection_graphics(self.connection_scene, self.connection_view, self.output_list, self.input_list, is_midi=False)

    def update_midi_connections(self):
        self._update_connection_graphics(self.midi_connection_scene, self.midi_connection_view, self.midi_output_list, self.midi_input_list, is_midi=True)


    def _update_connection_graphics(self, scene, view, output_list, input_list, is_midi):
        scene.clear()
        view_rect = view.rect()
        scene_rect = QRectF(0, 0, view_rect.width(), view_rect.height())
        scene.setSceneRect(scene_rect)

        connections = []
        ports = self.client.get_ports()
        for output_port in ports:
            if output_port.is_output and output_port.is_midi == is_midi:
                for input_port in self.client.get_all_connections(output_port):
                    if input_port.is_input and input_port.is_midi == is_midi:
                        connections.append((output_port.name, input_port.name))

        for output_name, input_name in connections:
            start_list = output_list
            end_list = input_list
            start_pos = self.get_port_position(start_list, output_name, view)
            end_pos = self.get_port_position(end_list, input_name, view)

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
                scene.addItem(path_item)
        view.fitInView(scene.sceneRect(), Qt.KeepAspectRatio)


    def on_input_clicked(self, item):
        self._on_port_clicked(item, self.input_list, self.output_list, False)

    def on_midi_input_clicked(self, item):
        self._on_port_clicked(item, self.midi_input_list, self.midi_output_list, True)

    def on_output_clicked(self, item):
        self._on_port_clicked(item, self.output_list, self.input_list, False)

    def on_midi_output_clicked(self, item):
        self._on_port_clicked(item, self.midi_output_list, self.midi_input_list, True)


    def _on_port_clicked(self, item, clicked_list, other_list, is_midi):
        if is_midi:
            self.clear_midi_highlights()
        else:
            self.clear_highlights()

        clicked_list.setCurrentItem(item)
        port_name = item.text()

        if is_midi:
            if clicked_list == self.midi_input_list:
                self.highlight_midi_input(port_name)
                self._highlight_connected_outputs_for_input(port_name, is_midi)
                self.update_midi_connection_buttons() # Updated here
            else:
                self.highlight_midi_output(port_name)
                self._highlight_connected_inputs_for_output(port_name, is_midi)
                self.update_midi_connection_buttons() # Updated here
        else:
            if clicked_list == self.input_list:
                self.highlight_input(port_name)
                self._highlight_connected_outputs_for_input(port_name, is_midi)
                self.update_connection_buttons() # Updated here
            else:
                self.highlight_output(port_name)
                self._highlight_connected_inputs_for_output(port_name, is_midi)
                self.update_connection_buttons() # Updated here


    def _highlight_connected_outputs_for_input(self, input_name, is_midi):
        output_ports = self.client.get_ports(is_output=True)
        for output_port in output_ports:
            if output_port.is_midi != is_midi:
                continue
            if input_name in [conn.name for conn in self.client.get_all_connections(output_port)]:
                if is_midi:
                    self.highlight_midi_output(output_port.name, auto_highlight=True)
                else:
                    self.highlight_output(output_port.name, auto_highlight=True)

    def _highlight_connected_inputs_for_output(self, output_name, is_midi):
        input_ports = [p for p in self.client.get_ports(is_input=True)]
        for input_port in input_ports:
            if input_port.is_midi != is_midi:
                continue
            if output_name in [c.name for c in self.client.get_all_connections(input_port)]:
                if is_midi:
                    self.highlight_midi_input(input_port.name, auto_highlight=True)
                else:
                    self.highlight_input(input_port.name, auto_highlight=True)


    def highlight_input(self, input_name, auto_highlight=False):
        self._highlight_list_item(self.input_list, input_name, auto_highlight)

    def highlight_output(self, output_name, auto_highlight=False):
        self._highlight_list_item(self.output_list, output_name, auto_highlight)

    def highlight_midi_input(self, input_name, auto_highlight=False):
        self._highlight_list_item(self.midi_input_list, input_name, auto_highlight)

    def highlight_midi_output(self, output_name, auto_highlight=False):
        self._highlight_list_item(self.midi_output_list, output_name, auto_highlight)

    def highlight_drop_target_item(self, list_widget, item):
        item.setBackground(QBrush(self.drag_highlight_color))

    def clear_drop_target_highlight(self, list_widget):
        for i in range(list_widget.count()):
            item = list_widget.item(i)
            item.setBackground(QBrush(self.background_color))


    def _highlight_list_item(self, list_widget, port_name, auto_highlight):
        for i in range(list_widget.count()):
            item = list_widget.item(i)
            if (isinstance(item, ElidedListWidgetItem) and item.full_text == port_name) or item.text() == port_name:
                item.setForeground(QBrush(self.highlight_color if not auto_highlight else self.auto_highlight_color)) # Changed to setForeground
                break


    def clear_highlights(self):
        self._clear_list_highlights(self.input_list)
        self._clear_list_highlights(self.output_list)

    def clear_midi_highlights(self):
        self._clear_list_highlights(self.midi_input_list)
        self._clear_list_highlights(self.midi_output_list)

    def _clear_list_highlights(self, list_widget):
        for i in range(list_widget.count()):
            item = list_widget.item(i)
            item.setForeground(QBrush(self.text_color)) # Changed to setForeground and use text_color


    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_connections()
        self.update_midi_connections()
        self.input_list.update_elided_text()
        self.output_list.update_elided_text()
        self.midi_input_list.update_elided_text()
        self.midi_output_list.update_elided_text()


    def update_connection_buttons(self): # Renamed and generalized function
        self._update_port_connection_buttons(self.input_list, self.output_list, self.connect_button, self.disconnect_button) # Pass connect_button

    def update_midi_connection_buttons(self): # Renamed and generalized function
        self._update_port_connection_buttons(self.midi_input_list, self.midi_output_list, self.midi_connect_button, self.midi_disconnect_button) # Pass midi_connect_button


    def _update_port_connection_buttons(self, input_list, output_list, connect_button, disconnect_button): # Modified to handle connect_button
        input_item = input_list.currentItem()
        output_item = output_list.currentItem()

        if input_item and output_item:
            output_name = output_item.text()
            input_name = input_item.text()
            connected = any(input_port.name == input_name for input_port in self.client.get_all_connections(output_name))
            disconnect_button.setEnabled(connected)
            connect_button.setEnabled(not connected) # Disable connect if already connected
        else:
            disconnect_button.setEnabled(False)
            connect_button.setEnabled(False) # Disable connect if no items selected

    def closeEvent(self, event):
        if self.minimize_on_close:
            event.ignore()
            self.hide() # Minimize to tray instead of closing
        else:
            event.accept()


def main():
    app = QApplication(sys.argv)
    window = JackConnectionManager()
    window.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
