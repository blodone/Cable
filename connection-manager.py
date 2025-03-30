import sys
import random
import re
import configparser
import os
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QListWidget, QPushButton, QLabel,
                             QGraphicsView, QGraphicsScene, QTabWidget, QListWidgetItem,
                             QGraphicsPathItem, QCheckBox, QMenu, QSizePolicy, QSpacerItem,
                             QButtonGroup, QTextEdit, QTreeWidget, QTreeWidgetItem, QLineEdit) # Added QLineEdit here
from PyQt6.QtCore import Qt, QMimeData, QPointF, QRectF, QTimer, QSize, QRect, QProcess, pyqtSignal, QPoint
from PyQt6.QtGui import (QDrag, QColor, QPainter, QBrush, QPalette, QPen,
                         QPainterPath, QFontMetrics, QFont, QAction, QPixmap, QGuiApplication)
import jack

# Add custom handler for unraisable exceptions
def custom_unraisable_hook(unraisable):
    """
    Custom handler for unraisable exceptions that filters out JACK callback errors
    """
    # Check if this is a JACK callback error we want to suppress
    if (isinstance(unraisable.exc_value, AssertionError) and
        'callback_wrapper' in str(unraisable.err_msg) and
        'jack.py' in str(unraisable.err_msg)):
        # Silently ignore these specific JACK callback assertion errors
        return

    # For other unraisable exceptions, use the default handler
    sys.__unraisablehook__(unraisable)

# Install the custom handler early
sys.unraisablehook = custom_unraisable_hook

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
            'auto_refresh_enabled': 'True',  # Add default for auto refresh
            'collapse_all_enabled': 'False'  # Add default for collapse all
        }

        for key, value in defaults.items():
            if key not in self.config['DEFAULT']:
                self.config['DEFAULT'][key] = value

        self.save_config()

    def save_config(self):
        with open(self.config_file, 'w') as configfile: # Corrected line 52: ' replaced with )
            self.config.write(configfile)

    def get_bool(self, key, default=True):
        return self.config['DEFAULT'].getboolean(key, default)

    def set_bool(self, key, value):
        self.config['DEFAULT'][key] = 'true' if value else 'false'
        self.save_config()


class ElidedListWidgetItem(QListWidgetItem):
    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.full_text = text
        self.setText(self.full_text)

    def elide_text(self, text, width):
        font_metrics = QFontMetrics(self.font())
        return font_metrics.elidedText(text, Qt.TextElideMode.ElideRight, width)

class PortTreeWidget(QTreeWidget):
    """A tree widget for displaying ports with collapsible groups"""
    itemDragged = pyqtSignal(QTreeWidgetItem)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumWidth(100)
        self._width = 150
        self.current_drag_highlight_item = None
        self.setHeaderHidden(True)
        self.setIndentation(15)
        self.port_groups = {}  # Maps group names to group items
        self.port_items = {}   # Maps port names to port items
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QTreeWidget.DragDropMode.DragDrop)  # Fixed: DragAndDrop → DragDrop
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        # Add tracking to improve drag behavior
        self.setMouseTracking(True)
        # Remember initially selected item to improve selection during drag operations
        self.initialSelection = None
        # Add storage for mouse press position
        self.mousePressPos = None

    def sizeHint(self):
        return QSize(self._width, 300)  # Default height

    def addPort(self, port_name):
        # Extract group name (everything before the colon)
        group_name = port_name.split(':', 1)[0] if ':' in port_name else "Ungrouped"

        # Create group if it doesn't exist
        if group_name not in self.port_groups:
            group_item = QTreeWidgetItem(self)
            group_item.setText(0, group_name)
            group_item.setFlags(group_item.flags() | Qt.ItemFlag.ItemIsAutoTristate)
            group_item.setExpanded(True)  # Expanded by default
            self.port_groups[group_name] = group_item

        # Add port as child of group
        port_item = QTreeWidgetItem(self.port_groups[group_name])
        port_item.setText(0, port_name)
        port_item.setData(0, Qt.ItemDataRole.UserRole, port_name)  # Store full port name
        self.port_items[port_name] = port_item

        return port_item

    def clear(self):
        super().clear()
        self.port_groups = {}
        self.port_items = {}

    def expandCollapseGroup(self, group_name, expand):
        """Expand or collapse a specific group by name"""
        group_item = self.port_groups.get(group_name)
        if group_item:
            group_item.setExpanded(expand)

    def expandAllGroups(self):
        """Expand all port groups"""
        for group_item in self.port_groups.values():
            group_item.setExpanded(True)

    def collapseAllGroups(self):
        """Collapse all port groups"""
        for group_item in self.port_groups.values():
            group_item.setExpanded(False)

    def show_context_menu(self, position):
        item = self.itemAt(position)
        if item:
            # Check if it's a port item (leaf node) or group item
            if item.childCount() == 0:  # Port item
                port_name = item.data(0, Qt.ItemDataRole.UserRole)
                menu = QMenu(self)
                disconnect_action = QAction("Disconnect all", self)
                disconnect_action.triggered.connect(lambda checked, name=port_name:
                                                  self.window().disconnect_node(name))
                menu.addAction(disconnect_action)
                menu.exec(self.mapToGlobal(position))
            else:  # Group item
                group_name = item.text(0)
                is_expanded = item.isExpanded()

                menu = QMenu(self)

                # Toggle expand/collapse for this specific group
                toggle_action = QAction("Collapse group" if is_expanded else "Expand group", self)
                toggle_action.triggered.connect(lambda: item.setExpanded(not is_expanded))

                # Actions for all groups
                expand_all_action = QAction("Expand all", self)
                collapse_all_action = QAction("Collapse all", self)
                expand_all_action.triggered.connect(self.expandAllGroups)
                collapse_all_action.triggered.connect(self.collapseAllGroups)

                menu.addAction(toggle_action)
                menu.addSeparator()
                menu.addAction(expand_all_action)
                menu.addAction(collapse_all_action)

                menu.exec(self.mapToGlobal(position))

    def getSelectedPortName(self):
        """Returns the port name of the currently selected item, or None if no port is selected"""
        item = self.currentItem()
        if item and item.childCount() == 0:  # It's a port item, not a group
            return item.data(0, Qt.ItemDataRole.UserRole)
        return None

    def getPortItemByName(self, port_name):
        """Returns the tree item for a given port name"""
        return self.port_items.get(port_name)

    def dragEnterEvent(self, event):
        if event.mimeData().hasText():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        if item and item != self.current_drag_highlight_item:
            self.window().clear_drop_target_highlight(self)
            self.window().highlight_drop_target_item(self, item)
            self.current_drag_highlight_item = item
        elif not item:
            self.window().clear_drop_target_highlight(self)
            self.current_drag_highlight_item = None
        super().dragMoveEvent(event)

    def dragLeaveEvent(self, event):
        self.window().clear_drop_target_highlight(self)
        self.current_drag_highlight_item = None
        super().dragLeaveEvent(event)

    def mousePressEvent(self, event):
        """Track initial item selection to improve drag operations"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.initialSelection = self.itemAt(event.pos())
            # Store the current mouse press position
            self.mousePressPos = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """Custom mouse move event to help with drag detection"""
        if event.buttons() & Qt.MouseButton.LeftButton and self.initialSelection and self.mousePressPos:
            # Only start drag if we've moved a minimum distance
            if (event.pos() - self.mousePressPos).manhattanLength() >= QApplication.startDragDistance():
                # Only allow drag from port items (not groups)
                if self.initialSelection.childCount() == 0:
                    self.startDrag()
        super().mouseMoveEvent(event)

class DragPortTreeWidget(PortTreeWidget):  # Output Tree
    def __init__(self, parent=None):
        super().__init__(parent)
        # Allow both drag and drop for bidirectional connections
        self.setDragDropMode(QTreeWidget.DragDropMode.DragDrop)
        self.setAcceptDrops(True)

    def startDrag(self, supportedActions=None):
        """Start drag operation with port name as data"""
        item = self.currentItem() or self.initialSelection
        if item and item.childCount() == 0:  # Only start drag for port items, not groups
            port_name = item.data(0, Qt.ItemDataRole.UserRole)
            mime_data = QMimeData()
            mime_data.setText(port_name)
            mime_data.setData("application/x-port-role", b"output")

            drag = QDrag(self)
            drag.setMimeData(mime_data)

            # Add visual feedback
            pixmap = item.icon(0).pixmap(32, 32) if item.icon(0) else None
            if not pixmap or pixmap.isNull():
                pixmap = QPixmap(70, 20)
                pixmap.fill(Qt.GlobalColor.transparent)
                painter = QPainter(pixmap)
                painter.setPen(self.palette().color(QPalette.ColorRole.Text))
                painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, item.text(0))
                painter.end()

            drag.setPixmap(pixmap)
            drag.setHotSpot(QPoint(pixmap.width() // 2, pixmap.height() // 2))

            result = drag.exec(Qt.DropAction.CopyAction)
            self.initialSelection = None

    def dragEnterEvent(self, event):
        """Handle drag enter events to determine if drop should be accepted"""
        if event.mimeData().hasText() and event.mimeData().hasFormat("application/x-port-role"):
            role = event.mimeData().data("application/x-port-role")
            if role == b"input":  # Only accept input ports for drops on output tree
                event.acceptProposedAction()
                return
        event.ignore()

    def dragMoveEvent(self, event):
        """Handle drag move events for visual feedback"""
        if not event.mimeData().hasFormat("application/x-port-role"):
            event.ignore()
            return

        item = self.itemAt(event.position().toPoint())
        if item and item != self.current_drag_highlight_item and item.childCount() == 0:
            self.window().clear_drop_target_highlight(self)
            self.window().highlight_drop_target_item(self, item)
            self.current_drag_highlight_item = item
            event.acceptProposedAction()
        elif not item or item.childCount() > 0:
            self.window().clear_drop_target_highlight(self)
            self.current_drag_highlight_item = None
            event.ignore()
        else:
            event.acceptProposedAction()

    def dropEvent(self, event):
        """Handle drop events to create connections"""
        if not event.mimeData().hasFormat("application/x-port-role"):
            event.ignore()
            return

        role = event.mimeData().data("application/x-port-role")
        if role != b"input":
            event.ignore()
            return

        input_name = event.mimeData().text()
        item = self.itemAt(event.position().toPoint())
        if item and item.childCount() == 0:
            output_name = item.data(0, Qt.ItemDataRole.UserRole)
            self.window().make_connection(output_name, input_name)
            event.acceptProposedAction()
        else:
            event.ignore()

        self.window().clear_drop_target_highlight(self)
        self.current_drag_highlight_item = None

class DropPortTreeWidget(PortTreeWidget):  # Input Tree
    def __init__(self, parent=None):
        super().__init__(parent)
        # Allow both drag and drop for bidirectional connections
        self.setDragDropMode(QTreeWidget.DragDropMode.DragDrop)
        self.setAcceptDrops(True)

    def startDrag(self, supportedActions=None):
        """Start drag operation with port name as data"""
        item = self.currentItem() or self.initialSelection
        if item and item.childCount() == 0:  # Only start drag for port items, not groups
            port_name = item.data(0, Qt.ItemDataRole.UserRole)
            mime_data = QMimeData()
            mime_data.setText(port_name)
            mime_data.setData("application/x-port-role", b"input")

            drag = QDrag(self)
            drag.setMimeData(mime_data)

            # Add visual feedback
            pixmap = item.icon(0).pixmap(32, 32) if item.icon(0) else None
            if not pixmap or pixmap.isNull():
                pixmap = QPixmap(70, 20)
                pixmap.fill(Qt.GlobalColor.transparent)
                painter = QPainter(pixmap)
                painter.setPen(self.palette().color(QPalette.ColorRole.Text))
                painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, item.text(0))
                painter.end()

            drag.setPixmap(pixmap)
            drag.setHotSpot(QPoint(pixmap.width() // 2, pixmap.height() // 2))

            result = drag.exec(Qt.DropAction.CopyAction)
            self.initialSelection = None

    def dragEnterEvent(self, event):
        """Handle drag enter events to determine if drop should be accepted"""
        if event.mimeData().hasText() and event.mimeData().hasFormat("application/x-port-role"):
            role = event.mimeData().data("application/x-port-role")
            if role == b"output":  # Only accept output ports for drops on input tree
                event.acceptProposedAction()
                return
        event.ignore()

    def dragMoveEvent(self, event):
        """Handle drag move events for visual feedback"""
        if not event.mimeData().hasFormat("application/x-port-role"):
            event.ignore()
            return

        item = self.itemAt(event.position().toPoint())
        if item and item != self.current_drag_highlight_item and item.childCount() == 0:
            self.window().clear_drop_target_highlight(self)
            self.window().highlight_drop_target_item(self, item)
            self.current_drag_highlight_item = item
            event.acceptProposedAction()
        elif not item or item.childCount() > 0:
            self.window().clear_drop_target_highlight(self)
            self.current_drag_highlight_item = None
            event.ignore()
        else:
            event.acceptProposedAction()

    def dropEvent(self, event):
        """Handle drop events to create connections"""
        if not event.mimeData().hasFormat("application/x-port-role"):
            event.ignore()
            return

        role = event.mimeData().data("application/x-port-role")
        if role != b"output":
            event.ignore()
            return

        output_name = event.mimeData().text()
        item = self.itemAt(event.position().toPoint())
        if item and item.childCount() == 0:
            input_name = item.data(0, Qt.ItemDataRole.UserRole)
            self.window().make_connection(output_name, input_name)
            event.acceptProposedAction()
        else:
            event.ignore()

        self.window().clear_drop_target_highlight(self)
        self.current_drag_highlight_item = None

class ConnectionView(QGraphicsView):
    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.refresh_timer = QTimer()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fitInView(self.scene().sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def start_refresh_timer(self, callback, interval=1):
        """Start the timer to refresh connections visualization"""
        self.refresh_timer.timeout.connect(callback)
        self.refresh_timer.start(interval)

    def stop_refresh_timer(self):
        """Stop the refresh timer"""
        self.refresh_timer.stop()
        if self.refresh_timer.receivers(self.refresh_timer.timeout) > 0:
            self.refresh_timer.timeout.disconnect()


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
    # PyQt signals for port registration events
    port_registered = pyqtSignal(str, bool)  # port name, is_input
    port_unregistered = pyqtSignal(str, bool)  # port name, is_input

    def __init__(self):
        super().__init__()
        self.config_manager = ConfigManager()
        self.minimize_on_close = True
        self.setWindowTitle('Cables')
        self.setGeometry(100, 100, 1368, 1000)
        self.initial_middle_width = 250
        self.port_type = 'audio'
        self.client = jack.Client('ConnectionManager')
        self.connections = set()
        self.connection_colors = {}
        self.connection_history = ConnectionHistory()
        self.dark_mode = self.is_dark_mode()
        self.setup_colors()
        self.callbacks_enabled = True

        # Create filter edit widgets (will be placed in bottom layout later)
        self.output_filter_edit = QLineEdit()
        self.output_filter_edit.setPlaceholderText("Filter outputs...")
        self.input_filter_edit = QLineEdit()
        self.input_filter_edit.setPlaceholderText("Filter inputs...")
        # Removed redundant MIDI filter edits - use the main ones above

        # Set up JACK port registration callbacks
        self.client.set_port_registration_callback(self._handle_port_registration)

        # Connect signals to refresh methods
        self.port_registered.connect(self._on_port_registered)
        self.port_unregistered.connect(self._on_port_unregistered)

        # Detect Flatpak environment
        self.flatpak_env = os.path.exists('/.flatpak-info')

        # Initialize process for pw-top and output buffer
        self.pw_process = None
        self.pwtop_buffer = ""  # Buffer to store pw-top output
        self.last_complete_cycle = None  # Store last complete cycle

        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        self.setCentralWidget(main_widget)
        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)

        self.audio_tab_widget = QWidget()
        self.midi_tab_widget = QWidget()
        self.pwtop_tab_widget = QWidget()

        self.setup_port_tab(self.audio_tab_widget, "Audio", 'audio')
        self.setup_port_tab(self.midi_tab_widget, "MIDI", 'midi')
        self.setup_pwtop_tab(self.pwtop_tab_widget)

        self.tab_widget.addTab(self.audio_tab_widget, "Audio")
        self.tab_widget.addTab(self.midi_tab_widget, "MIDI")
        self.tab_widget.addTab(self.pwtop_tab_widget, "pw-top")
        self.tab_widget.currentChanged.connect(self.switch_tab)

        self.setup_bottom_layout(main_layout)

        # Initialize the startup refresh timer
        self.startup_refresh_timer = QTimer()
        self.startup_refresh_timer.timeout.connect(self.startup_refresh)
        self.startup_refresh_count = 0

        # Visualization refresh timers will be started conditionally later based on config

        # Activate JACK client and start refresh sequence
        self.client.activate()

        # Start the rapid refresh sequence immediately
        self.start_startup_refresh()

    def start_startup_refresh(self):
        """Start the rapid refresh sequence on startup"""
        self.startup_refresh_count = 0
        self.startup_refresh_timer.start(1)  # 1ms interval

    def startup_refresh(self):
        """Handle the rapid refresh sequence"""
        # Remember original port type
        original_port_type = self.port_type

        # First refresh audio ports
        self.port_type = 'audio'
        self.refresh_ports()

        # Then refresh MIDI ports
        self.port_type = 'midi'
        self.refresh_ports()

        # Restore original port type
        self.port_type = original_port_type

        # Update current tab's view
        self.refresh_visualizations()

        # Increment counter and stop timer if done
        self.startup_refresh_count += 1
        if self.startup_refresh_count >= 3:
            self.startup_refresh_timer.stop()

            # Apply collapse state after startup refresh is complete
            if hasattr(self, 'collapse_all_checkbox') and self.collapse_all_checkbox.isChecked():
                self.apply_collapse_state_to_all_trees()

    def setup_pwtop_tab(self, tab_widget):
        """Set up the pw-top statistics tab"""
        layout = QVBoxLayout(tab_widget)

        # Create text display widget
        self.pwtop_text = QTextEdit()
        self.pwtop_text.setReadOnly(True)
        self.pwtop_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: {self.background_color.name()};
                color: {self.text_color.name()};
                font-family: monospace;
                font-size: 13pt;
            }}
        """)

        layout.addWidget(self.pwtop_text)

        # Start pw-top process when tab is created
        self.start_pwtop_process()

    def start_pwtop_process(self):
        """Start the pw-top process in batch mode"""
        if self.pw_process is None:
            self.pw_process = QProcess()

            if self.flatpak_env:
                self.pw_process.setProgram("flatpak-spawn")
                self.pw_process.setArguments(["--host", "pw-top", "-b"])
            else:
                self.pw_process.setProgram("pw-top")
                self.pw_process.setArguments(["-b"])

            self.pw_process.readyReadStandardOutput.connect(self.handle_pwtop_output)
            self.pw_process.errorOccurred.connect(self.handle_pwtop_error)
            self.pw_process.finished.connect(self.handle_pwtop_finished)
            self.pw_process.start()

    def stop_pwtop_process(self):
        """Stop the pw-top process"""
        if self.pw_process is not None:
            # Close process standard I/O channels
            self.pw_process.closeReadChannel(QProcess.ProcessChannel.StandardOutput)
            self.pw_process.closeReadChannel(QProcess.ProcessChannel.StandardError)
            self.pw_process.closeWriteChannel()

            # Terminate gracefully first
            self.pw_process.terminate()

            # Give it some time to terminate gracefully
            if not self.pw_process.waitForFinished(1000):
                # Force kill if it doesn't terminate
                self.pw_process.kill()
                self.pw_process.waitForFinished()
            self.pw_process = None

    def handle_pwtop_output(self):
        """Handle new output from pw-top"""
        if self.pw_process is not None:
            data = self.pw_process.readAllStandardOutput().data().decode()
            if data:
                # Append new data to buffer
                self.pwtop_buffer += data

                # Extract complete cycle
                complete_cycle = self.extract_latest_complete_cycle()

                # Update our stored complete cycle if we found a new one
                if complete_cycle:
                    self.last_complete_cycle = complete_cycle

                # Always display the latest known complete cycle
                if self.last_complete_cycle:
                    self.pwtop_text.setText(self.last_complete_cycle)
                    # Keep cursor at the top to maintain stable view
                    self.pwtop_text.verticalScrollBar().setValue(0)

                # Limit buffer size to prevent memory issues
                if len(self.pwtop_buffer) > 10000:
                    self.pwtop_buffer = self.pwtop_buffer[-5000:]

    def handle_pwtop_error(self, error):
        """Handle pw-top process errors"""
        print(f"pw-top process error: {error}")

    def handle_pwtop_finished(self, exit_code, exit_status):
        """Handle pw-top process completion"""
        print(f"pw-top process finished - Exit code: {exit_code}, Status: {exit_status}")

    def extract_latest_complete_cycle(self):
        """Extract the latest complete cycle from the pw-top output buffer"""
        lines = self.pwtop_buffer.split('\n')

        # Find all lines that start with 'S' and contain 'ID' and 'NAME'
        header_indices = [
            i for i, line in enumerate(lines)
            if line.startswith('S') and 'ID' in line and 'NAME' in line
        ]

        # Keep buffer size manageable by removing old data
        if len(header_indices) > 2:
            keep_from_line = header_indices[-2]  # Keep last 2 cycles
            self.pwtop_buffer = '\n'.join(lines[keep_from_line:])

        # Need at least 2 headers to identify a complete cycle
        if len(header_indices) < 2:
            return None

        # Extract section between last two headers
        start_idx = header_indices[-2]
        end_idx = header_indices[-1]
        section = lines[start_idx:end_idx]

        # Basic validation - should have some minimum content
        if len(section) < 3:
            return None

        return '\n'.join(section)

    def update_pwtop_output(self):
        """Handle pw-top output updates"""
        if self.pw_process is not None:
            self.handle_pwtop_output()

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

        # Replace list widgets with tree widgets
        input_tree = DropPortTreeWidget()
        output_tree = DragPortTreeWidget()
        connection_scene = QGraphicsScene()
        connection_view = ConnectionView(connection_scene)

        input_tree.setStyleSheet(self.list_stylesheet())
        output_tree.setStyleSheet(self.list_stylesheet())
        connection_view.setStyleSheet(f"background: {self.background_color.name()}; border: none;")

        input_layout.addSpacerItem(QSpacerItem(20, 17, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed))
        output_layout.addSpacerItem(QSpacerItem(20, 17, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed))

        input_layout.addWidget(input_label)
        input_layout.addWidget(input_tree)
        # Input filter box (self.input_filter_edit/self.midi_input_filter_edit) created in __init__


        output_layout.addWidget(output_label)
        output_layout.addWidget(output_tree)
        # Output filter box (self.output_filter_edit/self.midi_output_filter_edit) created in __init__


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
        middle_layout.addLayout(button_layout)
        middle_layout.addWidget(connection_view)

        middle_layout_widget = QWidget()
        middle_layout_widget.setLayout(middle_layout)
        middle_layout_widget.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        middle_layout_widget.setFixedWidth(self.initial_middle_width)

        content_layout = QHBoxLayout()
        content_layout.addLayout(output_layout)
        content_layout.addWidget(middle_layout_widget)
        content_layout.addLayout(input_layout)
        layout.addLayout(content_layout)

        if port_type == 'audio':
            self.input_tree = input_tree
            self.output_tree = output_tree
            self.connection_scene = connection_scene
            self.connection_view = connection_view
            self.connect_button = connect_button
            self.disconnect_button = disconnect_button
            self.refresh_button = refresh_button
            # References (self.input_filter_edit, self.output_filter_edit) created in __init__

            input_tree.itemClicked.connect(self.on_input_clicked)
            output_tree.itemClicked.connect(self.on_output_clicked)
            connect_button.clicked.connect(self.make_connection_selected)
            disconnect_button.clicked.connect(self.break_connection_selected)
            refresh_button.clicked.connect(self.refresh_ports)
            # Connect filter signals using instance attributes to a new handler
            # Disconnect previous connections first to avoid duplicates if setup is called multiple times (unlikely but safe)
            try: self.input_filter_edit.textChanged.disconnect()
            except TypeError: pass # No connection existed
            try: self.output_filter_edit.textChanged.disconnect()
            except TypeError: pass # No connection existed

            self.input_filter_edit.textChanged.connect(self._handle_filter_change)
            self.output_filter_edit.textChanged.connect(self._handle_filter_change)
        elif port_type == 'midi':
            self.midi_input_tree = input_tree
            self.midi_output_tree = output_tree
            self.midi_connection_scene = connection_scene
            self.midi_connection_view = connection_view
            self.midi_connect_button = connect_button
            self.midi_disconnect_button = disconnect_button
            # References (self.midi_input_filter_edit, self.midi_output_filter_edit) created in __init__

            input_tree.itemClicked.connect(self.on_midi_input_clicked)
            output_tree.itemClicked.connect(self.on_midi_output_clicked)
            connect_button.clicked.connect(self.make_midi_connection_selected)
            disconnect_button.clicked.connect(self.break_midi_connection_selected)
            refresh_button.clicked.connect(self.refresh_ports)
            # Filter signals are connected in the 'audio' block to the shared handler

    def setup_bottom_layout(self, main_layout):
        bottom_layout = QHBoxLayout()

        # Auto Refresh checkbox
        self.auto_refresh_checkbox = QCheckBox('Auto Refresh')
        # Load auto refresh state from config
        auto_refresh_enabled = self.config_manager.get_bool('auto_refresh_enabled', True)
        self.auto_refresh_checkbox.setChecked(auto_refresh_enabled)

        # Collapse All toggle
        self.collapse_all_checkbox = QCheckBox('Collapse All')
        # Load collapse all state from config
        collapse_all_enabled = self.config_manager.get_bool('collapse_all_enabled', False)
        self.collapse_all_checkbox.setChecked(collapse_all_enabled)
        self.collapse_all_checkbox.stateChanged.connect(self.toggle_collapse_all)

        # Undo/Redo buttons
        self.undo_button = QPushButton('Undo')
        self.redo_button = QPushButton('Redo')
        button_size = self.connect_button.sizeHint()
        self.undo_button.setFixedSize(button_size)
        self.redo_button.setFixedSize(button_size)

        for button in [self.undo_button, self.redo_button]:
            button.setStyleSheet(self.button_stylesheet())
            button.setEnabled(False)

        # Define style for filter edits
        filter_style = f"""
            QLineEdit {{
                background-color: {self.background_color.name()};
                color: {self.text_color.name()};
                border: 1px solid {self.text_color.name()};
                padding: 2px;
                border-radius: 3px;
            }}
        """
        # Use the filter edits created in setup_port_tab
        # Apply style and fixed width
        if hasattr(self, 'output_filter_edit'):
            self.output_filter_edit.setStyleSheet(filter_style)
            self.output_filter_edit.setClearButtonEnabled(True) # Add clear button
            self.output_filter_edit.setFixedWidth(150)
            bottom_layout.addWidget(self.output_filter_edit) # Add output filter to the far left

        bottom_layout.addStretch(1) # Push central controls away from left filter
        bottom_layout.addWidget(self.auto_refresh_checkbox)
        bottom_layout.addWidget(self.collapse_all_checkbox)
        bottom_layout.addWidget(self.undo_button)
        bottom_layout.addWidget(self.redo_button)
        bottom_layout.addStretch(1) # Push input filter away from central controls

        if hasattr(self, 'input_filter_edit'):
            self.input_filter_edit.setStyleSheet(filter_style)
            self.input_filter_edit.setClearButtonEnabled(True) # Add clear button
            self.input_filter_edit.setFixedWidth(150)
            bottom_layout.addWidget(self.input_filter_edit) # Add input filter to the far right

        main_layout.addLayout(bottom_layout)

        self.auto_refresh_checkbox.stateChanged.connect(self.toggle_auto_refresh)
        self.undo_button.clicked.connect(self.undo_action)
        self.redo_button.clicked.connect(self.redo_action)

        # Initialize callback state from config
        self.callbacks_enabled = auto_refresh_enabled

        # Initialize visibility based on current tab
        # This ensures controls are hidden if we start directly on pw-top tab
        current_tab = self.tab_widget.currentIndex() if hasattr(self, 'tab_widget') else 0
        self.show_bottom_controls(current_tab < 2)

        # Start visualization timers if auto-refresh is enabled in config
        if auto_refresh_enabled:
            self.connection_view.start_refresh_timer(self.refresh_visualizations)
            self.midi_connection_view.start_refresh_timer(self.refresh_visualizations)

    # Add new method to apply collapse state to all trees
    def apply_collapse_state_to_all_trees(self):
        """Apply the current collapse state to all port trees"""
        if hasattr(self, 'collapse_all_checkbox') and self.collapse_all_checkbox.isChecked():
            # Collapse all trees regardless of current tab
            if hasattr(self, 'input_tree'):
                self.input_tree.collapseAllGroups()
            if hasattr(self, 'output_tree'):
                self.output_tree.collapseAllGroups()
            if hasattr(self, 'midi_input_tree'):
                self.midi_input_tree.collapseAllGroups()
            if hasattr(self, 'midi_output_tree'):
                self.midi_output_tree.collapseAllGroups()
        else:
            # Expand all trees
            if hasattr(self, 'input_tree'):
                self.input_tree.expandAllGroups()
            if hasattr(self, 'output_tree'):
                self.output_tree.expandAllGroups()
            if hasattr(self, 'midi_input_tree'):
                self.midi_input_tree.expandAllGroups()
            if hasattr(self, 'midi_output_tree'):
                self.midi_output_tree.expandAllGroups()

        # Update visualizations
        self.refresh_visualizations()

    def toggle_collapse_all(self, state):
        """Handle collapse all toggle state change"""
        is_checked = int(state) == 2  # Qt.CheckState.Checked equals 2

        # Apply to all trees
        self.apply_collapse_state_to_all_trees()

        # Save state to config
        self.config_manager.set_bool('collapse_all_enabled', is_checked)

    def switch_tab(self, index):
        if (index < 2):  # Audio or MIDI tabs
            if hasattr(self, 'pw_process') and self.pw_process is not None:
                self.stop_pwtop_process()  # Stop pw-top when switching away
            self.port_type = 'audio' if index == 0 else 'midi'

            # Apply collapse state when switching tabs
            self.apply_collapse_state_to_all_trees()

            # Refresh the visualization immediately on tab switch
            self.refresh_visualizations()

            # Show bottom controls for non-pw-top tabs
            self.show_bottom_controls(True)
        elif index == 2:  # PipeWire Stats tab
            if self.pw_process is None:
                self.start_pwtop_process()

            # Hide bottom controls for pw-top tab
            self.show_bottom_controls(False)

    def show_bottom_controls(self, visible):
        """Show or hide bottom controls based on active tab"""
        if hasattr(self, 'auto_refresh_checkbox'):
            self.auto_refresh_checkbox.setVisible(visible)
        if hasattr(self, 'collapse_all_checkbox'):
            self.collapse_all_checkbox.setVisible(visible)
        if hasattr(self, 'undo_button'):
            self.undo_button.setVisible(visible)
        if hasattr(self, 'redo_button'):
            self.redo_button.setVisible(visible)
        # Also show/hide the filter edits
        if hasattr(self, 'output_filter_edit'):
            self.output_filter_edit.setVisible(visible)
        if hasattr(self, 'input_filter_edit'):
            self.input_filter_edit.setVisible(visible)
        # Removed references to non-existent MIDI filter edits


    def _handle_port_registration(self, port, register: bool):
        """JACK callback for port registration events. This runs in JACK's thread."""
        try:
            # If port is None or not fully initialized, skip processing
            if port is None:
                return

            # Check if the port object has the required attributes before accessing them
            # This will avoid the AssertionError in jack.py's _wrap_port_ptr
            port_name = None
            is_input = False

            # Use hasattr checks first to avoid triggering AttributeErrors
            if hasattr(port, 'name'):
                try:
                    port_name = port.name
                    # Only proceed if we got a valid port name
                    if not isinstance(port_name, str) or not port_name:
                        return
                except Exception:
                    return

            if hasattr(port, 'is_input'):
                try:
                    is_input = port.is_input
                except Exception:
                    # Default to False if we can't determine input status
                    is_input = False

            # Only emit signals if we successfully obtained port information
            if port_name:
                if register:
                    self.port_registered.emit(port_name, is_input)
                else:
                    self.port_unregistered.emit(port_name, is_input)
        except Exception as e:
            # Log any errors since this runs in a callback
            print(f"Port registration callback error: {type(e).__name__}: {e}")

    def _on_port_registered(self, port_name: str, is_input: bool):
        """Handle port registration events in the Qt main thread"""
        if not self.callbacks_enabled:
            return
        if self.port_type == 'midi' and 'midi' not in port_name:
            return
        if self.port_type == 'audio' and 'midi' in port_name:
            return
        self.refresh_ports()

    def _on_port_unregistered(self, port_name: str, is_input: bool):
        """Handle port unregistration events in the Qt main thread"""
        if not self.callbacks_enabled:
            return
        if self.port_type == 'midi' and 'midi' not in port_name:
            return
        if self.port_type == 'audio' and 'midi' in port_name:
            return
        self.refresh_ports()

    def toggle_auto_refresh(self, state):
        is_checked = int(state) == 2  # Qt.CheckState.Checked equals 2
        self.callbacks_enabled = is_checked

        # Start or stop visualization timers based on state
        if is_checked:
            self.connection_view.start_refresh_timer(self.refresh_visualizations)
            self.midi_connection_view.start_refresh_timer(self.refresh_visualizations)
        else:
            self.connection_view.stop_refresh_timer()
            self.midi_connection_view.stop_refresh_timer()

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
            self.connection_color = QColor(0, 150, 255)  # Brighter blue for dark mode
            self.auto_highlight_color = QColor(255, 200, 0)  # Brighter orange
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
            current_input_port = self.input_tree.getSelectedPortName() if hasattr(self, 'input_tree') else None
            current_output_port = self.output_tree.getSelectedPortName() if hasattr(self, 'output_tree') else None
            current_input_filter = self.input_filter_edit.text() if hasattr(self, 'input_filter_edit') else ""
            current_output_filter = self.output_filter_edit.text() if hasattr(self, 'output_filter_edit') else ""

            self.input_tree.clear()
            self.output_tree.clear()

            input_ports, output_ports = self._get_ports(is_midi=False)

            for input_port in input_ports:
                self.input_tree.addPort(input_port)

            for output_port in output_ports:
                self.output_tree.addPort(output_port)

            # Re-apply filter after repopulating
            self.filter_ports(self.input_tree, current_input_filter)
            self.filter_ports(self.output_tree, current_output_filter)

            # Restore selection if ports still exist and are visible
            if current_input_port and current_input_port in self.input_tree.port_items:
                item = self.input_tree.port_items[current_input_port]
                if not item.isHidden():
                    self.input_tree.setCurrentItem(item)

            if current_output_port and current_output_port in self.output_tree.port_items:
                item = self.output_tree.port_items[current_output_port]
                if not item.isHidden():
                    self.output_tree.setCurrentItem(item)

            self.update_connections()
            self.clear_highlights()
            self.update_connection_buttons()
            self._highlight_connected_ports(current_input_port, current_output_port, is_midi=False)

        elif self.port_type == 'midi':
            current_input_port = self.midi_input_tree.getSelectedPortName() if hasattr(self, 'midi_input_tree') else None
            current_output_port = self.midi_output_tree.getSelectedPortName() if hasattr(self, 'midi_output_tree') else None
            current_input_filter = self.midi_input_filter_edit.text() if hasattr(self, 'midi_input_filter_edit') else ""
            current_output_filter = self.midi_output_filter_edit.text() if hasattr(self, 'midi_output_filter_edit') else ""

            self.midi_input_tree.clear()
            self.midi_output_tree.clear()

            input_ports, output_ports = self._get_ports(is_midi=True)

            for input_port in input_ports:
                self.midi_input_tree.addPort(input_port)

            for output_port in output_ports:
                self.midi_output_tree.addPort(output_port)

            # Re-apply filter after repopulating
            self.filter_ports(self.midi_input_tree, current_input_filter)
            self.filter_ports(self.midi_output_tree, current_output_filter)

            # Restore selection if ports still exist and are visible
            if current_input_port and current_input_port in self.midi_input_tree.port_items:
                item = self.midi_input_tree.port_items[current_input_port]
                if not item.isHidden():
                    self.midi_input_tree.setCurrentItem(item)

            if current_output_port and current_output_port in self.midi_output_tree.port_items:
                item = self.midi_output_tree.port_items[current_output_port]
                if not item.isHidden():
                    self.midi_output_tree.setCurrentItem(item)

            self.update_midi_connections()
            self.clear_midi_highlights()
            self.update_midi_connection_buttons()
            self._highlight_connected_ports(current_input_port, current_output_port, is_midi=True)

        # Maintain collapse state after refresh if collapse all is enabled
        if hasattr(self, 'collapse_all_checkbox') and self.collapse_all_checkbox.isChecked():
            self.apply_collapse_state_to_current_trees()

    # Add a new helper method to apply collapse state only to the current tab's trees
    def apply_collapse_state_to_current_trees(self):
        """Apply the collapse state to the currently visible trees only"""
        if self.port_type == 'audio':
            if hasattr(self, 'input_tree') and self.collapse_all_checkbox.isChecked():
                self.input_tree.collapseAllGroups()
            elif hasattr(self, 'input_tree'):
                self.input_tree.expandAllGroups()

            if hasattr(self, 'output_tree') and self.collapse_all_checkbox.isChecked():
                self.output_tree.collapseAllGroups()
            elif hasattr(self, 'output_tree'):
                self.output_tree.expandAllGroups()
        elif self.port_type == 'midi':
            if hasattr(self, 'midi_input_tree') and self.collapse_all_checkbox.isChecked():
                self.midi_input_tree.collapseAllGroups()
            elif hasattr(self, 'midi_input_tree'):
                self.midi_input_tree.expandAllGroups()

            if hasattr(self, 'midi_output_tree') and self.collapse_all_checkbox.isChecked():
                self.midi_output_tree.collapseAllGroups()
            elif hasattr(self, 'midi_output_tree'):
                self.midi_output_tree.expandAllGroups()

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
        try:
            # Get input ports
            ports = self.client.get_ports(is_input=True, is_midi=is_midi)
            input_ports = [port.name for port in ports if port is not None]

            # Get output ports
            ports = self.client.get_ports(is_output=True, is_midi=is_midi)
            output_ports = [port.name for port in ports if port is not None]

            # Additional MIDI filtering for safety
            if is_midi:
                input_ports = [p for p in input_ports if 'midi' in p.lower()]
                output_ports = [p for p in output_ports if 'midi' in p.lower()]
            else:
                input_ports = [p for p in input_ports if 'midi' not in p.lower()]
                output_ports = [p for p in output_ports if 'midi' not in p.lower()]

            input_ports = self._sort_ports(input_ports)
            output_ports = self._sort_ports(output_ports)
        except jack.JackError as e:
            print(f"Error getting ports: {e}")
            # Return current lists even if incomplete
            pass

        return input_ports, output_ports

    def _highlight_connected_ports(self, current_input_text, current_output_text, is_midi):
        try:
            if current_input_text:
                # Get only relevant output ports
                output_ports = self.client.get_ports(is_output=True, is_midi=is_midi)
                for output_port in output_ports:
                    try:
                        connections = self.client.get_all_connections(output_port)
                        if current_input_text in [c.name for c in connections]:
                            if is_midi:
                                self.highlight_midi_output(output_port.name, auto_highlight=True)
                            else:
                                self.highlight_output(output_port.name, auto_highlight=True)
                    except jack.JackError:
                        continue
            if current_output_text:
                # Get only relevant input ports
                input_ports = self.client.get_ports(is_input=True, is_midi=is_midi)
                for input_port in input_ports:
                    try:
                        connections = self.client.get_all_connections(input_port)
                        if current_output_text in [c.name for c in connections]:
                            if is_midi:
                                self.highlight_midi_input(input_port.name, auto_highlight=True)
                            else:
                                self.highlight_input(input_port.name, auto_highlight=True)
                    except jack.JackError:
                        continue
        except jack.JackError as e:
            print(f"Error highlighting connected ports: {e}")

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
                # Check if connection already exists before attempting to connect
                try:
                    connections = self.client.get_all_connections(output_name)
                    if any(conn.name == input_name for conn in connections):
                        print(f"Connection {output_name} -> {input_name} already exists, skipping")
                        return
                except jack.JackError:
                    # If we can't check connections, try the connect anyway
                    pass

                self.client.connect(output_name, input_name)
                self.connection_history.add_action('connect', output_name, input_name)
            else:
                self.client.disconnect(output_name, input_name)
                self.connection_history.add_action('disconnect', output_name, input_name)

            self.update_undo_redo_buttons()
            self.update_connections()
            self.refresh_ports()
            self.update_connection_buttons()
            self.update_midi_connection_buttons()

        except jack.JackError as e:
            print(f"{operation_type.capitalize()} error: {e}")
            # Don't crash on connection errors, just log them

    def make_connection_selected(self):
        input_port = self.input_tree.getSelectedPortName()
        output_port = self.output_tree.getSelectedPortName()
        if input_port and output_port:
            self.make_connection(output_port, input_port)

    def make_midi_connection_selected(self):
        input_port = self.midi_input_tree.getSelectedPortName()
        output_port = self.midi_output_tree.getSelectedPortName()
        if input_port and output_port:
            self.make_midi_connection(output_port, input_port)

    def break_connection_selected(self):
        input_port = self.input_tree.getSelectedPortName()
        output_port = self.output_tree.getSelectedPortName()
        if input_port and output_port:
            self.break_connection(output_port, input_port)

    def break_midi_connection_selected(self):
        input_port = self.midi_input_tree.getSelectedPortName()
        output_port = self.midi_output_tree.getSelectedPortName()
        if input_port and output_port:
            self.break_midi_connection(output_port, input_port)

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


    def get_port_position(self, tree_widget, port_name, connection_view):
        """Get the position of a port in the tree widget for drawing connections"""
        port_item = tree_widget.port_items.get(port_name)
        if not port_item:
            return None

        # Get the parent group item
        parent_group = port_item.parent()
        if not parent_group:
            return None

        # Check if the parent group is expanded
        is_expanded = parent_group.isExpanded()

        # If the group is collapsed, use the group's position instead
        target_item = port_item if is_expanded else parent_group

        # Get the rectangle for the item
        rect = tree_widget.visualItemRect(target_item)

        # If the rect has zero height (item not visible), return None
        if rect.height() <= 0:
            return None

        is_output = tree_widget in (self.output_tree, self.midi_output_tree)

        # Calculate the point at the middle-right or middle-left of the item
        point = QPointF(tree_widget.viewport().width() if is_output else 0,
                       rect.top() + rect.height() / 2)

        viewport_point = tree_widget.viewport().mapToParent(point.toPoint())
        global_point = tree_widget.mapToGlobal(viewport_point)
        scene_point = connection_view.mapFromGlobal(global_point)
        return connection_view.mapToScene(scene_point)

    def get_random_color(self, base_name):
        random.seed(base_name)
        return QColor(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))

    def update_connections(self):
        self._update_connection_graphics(self.connection_scene, self.connection_view,
                                        self.output_tree, self.input_tree, is_midi=False)

    def update_midi_connections(self):
        self._update_connection_graphics(self.midi_connection_scene, self.midi_connection_view,
                                        self.midi_output_tree, self.midi_input_tree, is_midi=True)

    def _update_connection_graphics(self, scene, view, output_tree, input_tree, is_midi):
        # Clear the scene first
        scene.clear()
        view_rect = view.rect()
        scene_rect = QRectF(0, 0, view_rect.width(), view_rect.height())
        scene.setSceneRect(scene_rect)

        # Get all connections
        connections = []
        try:
            ports = self.client.get_ports()
            for output_port in ports:
                if output_port.is_output and output_port.is_midi == is_midi:
                    for input_port in self.client.get_all_connections(output_port):
                        if input_port.is_input and input_port.is_midi == is_midi:
                            connections.append((output_port.name, input_port.name))
        except jack.JackError as e:
            print(f"Error getting connections: {e}")
            return

        # Draw each connection
        for output_name, input_name in connections:
            start_pos = self.get_port_position(output_tree, output_name, view)
            end_pos = self.get_port_position(input_tree, input_name, view)

            # Only draw connections where both ends are visible
            if start_pos and end_pos:
                path = QPainterPath()
                path.moveTo(start_pos)

                # Calculate control points for a smooth curve
                ctrl1_x = start_pos.x() + (end_pos.x() - start_pos.x()) / 3
                ctrl2_x = start_pos.x() + 2 * (end_pos.x() - start_pos.x()) / 3

                path.cubicTo(
                    QPointF(ctrl1_x, start_pos.y()),
                    QPointF(ctrl2_x, end_pos.y()),
                    end_pos
                )

                # Use a consistent color for connections from the same source
                base_name = output_name.rsplit(':', 1)[0]

                # Get a base random color
                random.seed(base_name)
                base_color = QColor(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))

                # Brighten the color in dark mode for better visibility
                if self.dark_mode:
                    # Make colors more vibrant and brighter in dark mode
                    h, s, v, a = base_color.getHsvF()
                    # Increase saturation and value for more vibrant appearance
                    s = min(1.0, s * 1.4)  # Increase saturation by 40%
                    v = min(1.0, v * 1.3)  # Increase brightness by 30%
                    base_color.setHsvF(h, s, v, a)

                pen = QPen(base_color, 2)
                path_item = QGraphicsPathItem(path)
                path_item.setPen(pen)
                scene.addItem(path_item)

        # Fit the view to show all connections
        view.fitInView(scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def on_input_clicked(self, item, column):
        self._on_port_clicked(item, self.input_tree, self.output_tree, False)

    def on_midi_input_clicked(self, item, column):
        self._on_port_clicked(item, self.midi_input_tree, self.midi_output_tree, True)

    def on_output_clicked(self, item, column):
        self._on_port_clicked(item, self.output_tree, self.input_tree, False)

    def on_midi_output_clicked(self, item, column):
        self._on_port_clicked(item, self.midi_output_tree, self.midi_input_tree, True)

    def _on_port_clicked(self, item, clicked_tree, other_tree, is_midi):
        """Handle port selection in tree widgets"""
        # Only process clicks on port items (not groups)
        if item.childCount() > 0:
            # This is a group item, not a port item
            return

        if is_midi:
            self.clear_midi_highlights()
        else:
            self.clear_highlights()

        clicked_tree.setCurrentItem(item)
        port_name = item.data(0, Qt.ItemDataRole.UserRole)

        if is_midi:
            if clicked_tree == self.midi_input_tree:
                self.highlight_midi_input(port_name)
                self._highlight_connected_outputs_for_input(port_name, is_midi)
                self.update_midi_connection_buttons()
            else:
                self.highlight_midi_output(port_name)
                self._highlight_connected_inputs_for_output(port_name, is_midi)
                self.update_midi_connection_buttons()
        else:
            if clicked_tree == self.input_tree:
                self.highlight_input(port_name)
                self._highlight_connected_outputs_for_input(port_name, is_midi)
                self.update_connection_buttons()
            else:
                self.highlight_output(port_name)
                self._highlight_connected_inputs_for_output(port_name, is_midi)
                self.update_connection_buttons()

    def _highlight_connected_outputs_for_input(self, input_name, is_midi):
        try:
            # Get only relevant output ports
            output_ports = self.client.get_ports(is_output=True, is_midi=is_midi)
            for output_port in output_ports:
                try:
                    connections = self.client.get_all_connections(output_port)
                    if input_name in [conn.name for conn in connections]:
                        if is_midi:
                            self.highlight_midi_output(output_port.name, auto_highlight=True)
                        else:
                            self.highlight_output(output_port.name, auto_highlight=True)
                except jack.JackError:
                    continue
        except jack.JackError as e:
            print(f"Error highlighting connected outputs: {e}")

    def _highlight_connected_inputs_for_output(self, output_name, is_midi):
        try:
            # Get only relevant input ports
            input_ports = self.client.get_ports(is_input=True, is_midi=is_midi)
            for input_port in input_ports:
                try:
                    connections = self.client.get_all_connections(input_port)
                    if output_name in [c.name for c in connections]:
                        if is_midi:
                            self.highlight_midi_input(input_port.name, auto_highlight=True)
                        else:
                            self.highlight_input(input_port.name, auto_highlight=True)
                except jack.JackError:
                    continue
        except jack.JackError as e:
            print(f"Error highlighting connected inputs: {e}")

    def highlight_input(self, input_name, auto_highlight=False):
        self._highlight_tree_item(self.input_tree, input_name, auto_highlight)

    def highlight_output(self, output_name, auto_highlight=False):
        self._highlight_tree_item(self.output_tree, output_name, auto_highlight)

    def highlight_midi_input(self, input_name, auto_highlight=False):
        self._highlight_tree_item(self.midi_input_tree, input_name, auto_highlight)

    def highlight_midi_output(self, output_name, auto_highlight=False):
        self._highlight_tree_item(self.midi_output_tree, output_name, auto_highlight)

    def highlight_drop_target_item(self, tree_widget, item):
        """Highlight an item when being dragged over"""
        item.setBackground(0, QBrush(self.drag_highlight_color))

    def clear_drop_target_highlight(self, tree_widget):
        """Clear drop target highlighting"""
        if isinstance(tree_widget, QTreeWidget):
            for i in range(tree_widget.topLevelItemCount()):
                group_item = tree_widget.topLevelItem(i)
                group_item.setBackground(0, QBrush(self.background_color))
                for j in range(group_item.childCount()):
                    child_item = group_item.child(j)
                    child_item.setBackground(0, QBrush(self.background_color))
        else:
            # Maintain compatibility with list widgets
            super().clear_drop_target_highlight(tree_widget)

    def _highlight_tree_item(self, tree_widget, port_name, auto_highlight=False):
        """Highlight a specific port item in a tree widget"""
        port_item = tree_widget.port_items.get(port_name)
        if port_item:
            port_item.setForeground(0, QBrush(
                self.highlight_color if not auto_highlight else self.auto_highlight_color))

    def clear_highlights(self):
        self._clear_tree_highlights(self.input_tree)
        self._clear_tree_highlights(self.output_tree)

    def clear_midi_highlights(self):
        self._clear_tree_highlights(self.midi_input_tree)
        self._clear_tree_highlights(self.midi_output_tree)

    def _clear_tree_highlights(self, tree_widget):
        """Clear highlights from all port items in a tree widget"""
        for i in range(tree_widget.topLevelItemCount()):
            group_item = tree_widget.topLevelItem(i)
            group_item.setForeground(0, QBrush(self.text_color))
            for j in range(group_item.childCount()):
                child_item = group_item.child(j)
                child_item.setForeground(0, QBrush(self.text_color))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_connections()
        self.update_midi_connections()

    def update_connection_buttons(self):
        self._update_port_connection_buttons(self.input_tree, self.output_tree,
                                           self.connect_button, self.disconnect_button)

    def update_midi_connection_buttons(self):
        self._update_port_connection_buttons(self.midi_input_tree, self.midi_output_tree,
                                           self.midi_connect_button, self.midi_disconnect_button)

    def _update_port_connection_buttons(self, input_tree, output_tree, connect_button, disconnect_button):
        """Update connection button states based on selected ports"""
        input_port = input_tree.getSelectedPortName()
        output_port = output_tree.getSelectedPortName()

        if input_port and output_port:
            try:
                # Check visibility as well - can't connect/disconnect hidden ports
                input_item = input_tree.getPortItemByName(input_port)
                output_item = output_tree.getPortItemByName(output_port)
                if input_item and output_item and not input_item.isHidden() and not output_item.isHidden():
                    connected = any(input_port == input_port_obj.name
                                  for input_port_obj in self.client.get_all_connections(output_port))
                    disconnect_button.setEnabled(connected)
                    connect_button.setEnabled(not connected)
                else:
                    disconnect_button.setEnabled(False)
                    connect_button.setEnabled(False)
            except jack.JackError:
                disconnect_button.setEnabled(False)
                connect_button.setEnabled(False)
        else:
            disconnect_button.setEnabled(False)
            connect_button.setEnabled(False)

    def _handle_filter_change(self):
        """Handles text changes in the shared filter boxes."""
        current_index = self.tab_widget.currentIndex()
        input_text = self.input_filter_edit.text()
        output_text = self.output_filter_edit.text()

        if current_index == 0:  # Audio tab
            if hasattr(self, 'input_tree'):
                self.filter_ports(self.input_tree, input_text)
            if hasattr(self, 'output_tree'):
                self.filter_ports(self.output_tree, output_text)
        elif current_index == 1:  # MIDI tab
            if hasattr(self, 'midi_input_tree'):
                self.filter_ports(self.midi_input_tree, input_text)
            if hasattr(self, 'midi_output_tree'):
                self.filter_ports(self.midi_output_tree, output_text)
        # No filtering needed for pw-top tab (index 2)

        # Refresh visualization after filtering
        # Note: filter_ports itself calls refresh_visualizations, so this might be redundant,
        # but keeping it here ensures visualization updates even if filter_ports logic changes.
        # Update: Removed redundant call as filter_ports handles it.
        # self.refresh_visualizations() # Redundant call removed

    def filter_ports(self, tree_widget, filter_text):
        """Filters the items in the specified tree widget based on the filter text."""
        filter_text = filter_text.lower() # Case-insensitive filtering

        # Iterate through all top-level items (groups)
        for i in range(tree_widget.topLevelItemCount()):
            group_item = tree_widget.topLevelItem(i)
            group_visible = False # Assume group is hidden unless a child matches

            # Iterate through children (ports) of the group
            for j in range(group_item.childCount()):
                port_item = group_item.child(j)
                port_name = port_item.data(0, Qt.ItemDataRole.UserRole) # Get full port name

                # Check if port name contains the filter text
                if filter_text in port_name.lower():
                    port_item.setHidden(False)
                    group_visible = True # Make group visible if at least one child is visible
                else:
                    port_item.setHidden(True)

            # Set the visibility of the group item
            group_item.setHidden(not group_visible)

        # After filtering, we need to refresh the connection visualization
        # because hidden items might affect line drawing positions.
        self.refresh_visualizations()

    def refresh_visualizations(self):
        """Refresh only the connection visualizations without refreshing ports"""
        if self.port_type == 'audio':
            self.update_connections()
        else:
            self.update_midi_connections()

    def closeEvent(self, event):
        """Handle window closing behavior"""
        if self.minimize_on_close:
            event.ignore()
            self.hide() # Minimize to tray instead of closing
        else:
            event.accept()
            QApplication.quit()

        # Clean up JACK client and deactivate callbacks
        if hasattr(self, 'client'):
            self.callbacks_enabled = False
            self.client.deactivate()
            self.client.close()

        # Stop the visualization refresh timers
        self.connection_view.stop_refresh_timer()
        self.midi_connection_view.stop_refresh_timer()

        # Stop pw-top process before closing
        if hasattr(self, 'pw_process') and self.pw_process is not None:
            self.stop_pwtop_process()

def main():
    # Redirect stderr to /dev/null to suppress JACK callback errors (redundant, but kept for safety):
    if not os.environ.get('DEBUG_JACK_CALLBACKS'):
        sys.stderr = open(os.devnull, 'w')

    app = QApplication(sys.argv)
    # Set the desktop filename for correct icon display in taskbar and window decorations
    QGuiApplication.setDesktopFileName("com.example.cable")
    window = JackConnectionManager()
    window.show()

    # Handle Ctrl+C gracefully
    import signal
    def signal_handler(signum, frame):
        print("Received signal to terminate")
        window.close()
        app.quit()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # Custom event loop that processes both Qt events and signals
        while window.isVisible():
            app.processEvents()
            # Small sleep to prevent CPU hogging
            from time import sleep
            sleep(0.001)  # 1ms sleep
        return 0
    except KeyboardInterrupt:
        print("Received keyboard interrupt")
        window.close()
        app.quit()
        return 1
    finally:
        # Ensure cleanup happens
        if window.pw_process is not None:
            window.stop_pwtop_process()
        if hasattr(window, 'client'):
            window.client.deactivate()
            window.client.close()

if __name__ == '__main__':
    sys.exit(main())
