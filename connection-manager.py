import sys
import random
import re
import configparser
import os
import shutil # Import shutil for command existence check
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QListWidget, QPushButton, QLabel,
                             QGraphicsView, QGraphicsScene, QTabWidget, QListWidgetItem,
                             QGraphicsPathItem, QCheckBox, QMenu, QSizePolicy, QSpacerItem,
                             QButtonGroup, QTextEdit, QTreeWidget, QTreeWidgetItem, QLineEdit,
                             QComboBox) # Added QLineEdit and QComboBox here
from PyQt6.QtCore import Qt, QMimeData, QPointF, QRectF, QTimer, QSize, QRect, QProcess, pyqtSignal, QPoint
from PyQt6.QtGui import (QDrag, QColor, QPainter, QBrush, QPalette, QPen,
                         QPainterPath, QFontMetrics, QFont, QAction, QPixmap, QGuiApplication, QTextCursor) # Added QTextCursor
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
        # Allow selecting multiple items with Ctrl/Shift
        self.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
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
                disconnect_action = QAction("Disconnect all from this port", self)
                disconnect_action.triggered.connect(lambda checked, name=port_name:
                                                  self.window().disconnect_node(name))
                menu.addAction(disconnect_action)
                menu.exec(self.mapToGlobal(position))
            else:  # Group item
                group_name = item.text(0)
                is_expanded = item.isExpanded()
                selected_items = self.selectedItems() # Get all selected items

                # Determine if the right-clicked item is part of the current selection
                is_current_item_selected = item in selected_items

                # If the right-clicked item wasn't selected, treat it as the only selection for the context menu
                target_items = selected_items if is_current_item_selected and len(selected_items) > 1 else [item]

                # Filter to only include group items from the target items
                target_group_items = [i for i in target_items if i.childCount() > 0]

                menu = QMenu(self)

                # Toggle expand/collapse for this specific group
                toggle_action = QAction("Collapse group" if is_expanded else "Expand group", self)
                toggle_action.triggered.connect(lambda: item.setExpanded(not is_expanded))

                # Actions for all groups
                expand_all_action = QAction("Expand all", self)
                collapse_all_action = QAction("Collapse all", self)
                expand_all_action.triggered.connect(self.expandAllGroups)
                collapse_all_action.triggered.connect(self.collapseAllGroups)

                # Action to disconnect all ports within the selected group(s)
                disconnect_group_action = QAction(f"Disconnect group{'s' if len(target_group_items) > 1 else ''}", self)
                # Disable if no actual group items are targeted (shouldn't happen with current logic, but safe)
                disconnect_group_action.setEnabled(bool(target_group_items))
                disconnect_group_action.triggered.connect(lambda: self.window().disconnect_selected_groups(target_group_items))

                menu.addAction(toggle_action)
                menu.addSeparator()
                menu.addAction(expand_all_action)
                menu.addAction(collapse_all_action)
                menu.addSeparator()
                menu.addAction(disconnect_group_action)

                menu.exec(self.mapToGlobal(position))

    def getSelectedPortNames(self):
        """Returns a list of port names for the currently selected port items."""
        selected_ports = []
        for item in self.selectedItems():
            # Only include actual port items (leaves), not groups
            if item and item.childCount() == 0:
                port_name = item.data(0, Qt.ItemDataRole.UserRole)
                if port_name:
                    selected_ports.append(port_name)
        return selected_ports

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
        # Store the current mouse press position regardless of button
        self.mousePressPos = event.pos()
        item_at_pos = self.itemAt(event.pos())

        if event.button() == Qt.MouseButton.LeftButton:
            self.initialSelection = item_at_pos # Remember item for potential drag start
            # Always call the superclass method for left clicks.
            # ExtendedSelection mode will interpret the Ctrl modifier correctly.
            super().mousePressEvent(event)
        else:
            # Handle other mouse buttons (e.g., right-click for context menu)
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
        """Start drag operation with port name or group data"""
        selected_items = self.selectedItems()
        if not selected_items:
            return

        # Filter out group items if multiple items are selected
        port_items = [item for item in selected_items if item.childCount() == 0]
        group_items = [item for item in selected_items if item.childCount() > 0]

        mime_data = QMimeData()
        drag_text = ""

        if len(port_items) > 1:
            # Dragging multiple ports
            port_names = [item.data(0, Qt.ItemDataRole.UserRole) for item in port_items if item.data(0, Qt.ItemDataRole.UserRole)]
            if not port_names: return # No valid ports selected

            mime_data.setData("application/x-port-list", b"true") # Indicate multiple ports
            mime_data.setData("application/x-port-role", b"output")
            mime_data.setText('\n'.join(port_names)) # Store port list
            drag_text = f"{len(port_names)} Output Ports" # Text for pixmap

        elif len(port_items) == 1 and not group_items:
            # Dragging a single port (original logic)
            item = port_items[0]
            port_name = item.data(0, Qt.ItemDataRole.UserRole)
            if not port_name: return # Don't drag invalid items

            mime_data.setData("application/x-port-role", b"output")
            mime_data.setText(port_name)
            drag_text = item.text(0) # Use displayed text for pixmap

        elif len(group_items) == 1 and not port_items:
            # Dragging a single group (original logic)
            item = group_items[0]
            group_name = item.text(0)
            port_list = self.window()._get_ports_in_group(item)
            if not port_list: return # Don't drag empty groups

            mime_data.setData("application/x-port-group", b"true")
            mime_data.setData("application/x-port-role", b"output")
            mime_data.setText('\n'.join(port_list)) # Store port list as newline-separated text
            drag_text = group_name # Text for pixmap

        else:
            # Invalid selection for dragging (e.g., mixed ports and groups, or nothing valid)
            return

        drag = QDrag(self)
        drag.setMimeData(mime_data)

        # Add visual feedback (using drag_text)
        # Create a generic pixmap for drag feedback
        font_metrics = QFontMetrics(self.font())
        text_width = font_metrics.horizontalAdvance(drag_text) + 10 # Add padding
        pixmap_width = max(70, text_width) # Ensure minimum width
        pixmap = QPixmap(pixmap_width, 20)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setPen(self.palette().color(QPalette.ColorRole.Text))
        # Use ElideRight if text is too long for the pixmap
        elided_text = font_metrics.elidedText(drag_text, Qt.TextElideMode.ElideRight, pixmap_width)
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, elided_text)
        painter.end()

        drag.setPixmap(pixmap)
        drag.setHotSpot(QPoint(pixmap.width() // 2, pixmap.height() // 2))

        result = drag.exec(Qt.DropAction.CopyAction)
        self.initialSelection = None # Clear selection after drag finishes

    def dragEnterEvent(self, event):
        """Handle drag enter events to determine if drop should be accepted"""
        mime_data = event.mimeData()
        is_port_drop = mime_data.hasFormat("application/x-port-role")
        is_port_list_drop = mime_data.hasFormat("application/x-port-list") # New check
        is_group_drop = mime_data.hasFormat("application/x-port-group")

        # Accept if it's a single port, a list of ports, or a group, AND the role is input
        if (is_port_drop or is_port_list_drop or is_group_drop):
            role = mime_data.data("application/x-port-role")
            if role == b"input":  # Only accept input ports/groups for drops on output tree
                event.acceptProposedAction()
                return

        event.ignore()

    def dragMoveEvent(self, event):
        """Handle drag move events for visual feedback, supporting ports and groups."""
        mime_data = event.mimeData()
        is_port_drag = mime_data.hasFormat("application/x-port-role") and not mime_data.hasFormat("application/x-port-list") # Single port
        is_port_list_drag = mime_data.hasFormat("application/x-port-list") # Multiple ports
        is_group_drag = mime_data.hasFormat("application/x-port-group")

        # 1. Check if it's a valid drag type we handle (Input role)
        if not (is_port_drag or is_port_list_drag or is_group_drag) or mime_data.data("application/x-port-role") != b"input":
            event.ignore()
            # Clear highlight if needed
            if self.current_drag_highlight_item:
                self.window().clear_drop_target_highlight(self)
                self.current_drag_highlight_item = None
            return

        # 2. Get item under cursor (Target item in Output tree)
        target_item = self.itemAt(event.position().toPoint())

        # 3. Determine if the target item is a valid drop target for the current drag source
        # Now, any target (port or group) is valid if the source is an Input port/group/list
        is_valid_target = bool(target_item)

        # 4. Handle highlighting and accepting/ignoring
        if is_valid_target:
            if target_item != self.current_drag_highlight_item:
                self.window().clear_drop_target_highlight(self)
                self.window().highlight_drop_target_item(self, target_item) # Highlight the valid target
                self.current_drag_highlight_item = target_item
            event.acceptProposedAction() # Accept move over valid target
        else:
            # Invalid target or no item under cursor
            if self.current_drag_highlight_item: # Clear highlight if there was one
                self.window().clear_drop_target_highlight(self)
                self.current_drag_highlight_item = None
            event.ignore() # Ignore move over invalid target

    def dropEvent(self, event):
        """Handle drop events to create connections for ports or groups."""
        mime_data = event.mimeData()
        is_port_drop = mime_data.hasFormat("application/x-port-role") and not mime_data.hasFormat("application/x-port-list") # Single port
        is_port_list_drop = mime_data.hasFormat("application/x-port-list") # Multiple ports
        is_group_drop = mime_data.hasFormat("application/x-port-group")

        # 1. Check validity (Source must be Input)
        if not (is_port_drop or is_port_list_drop or is_group_drop) or mime_data.data("application/x-port-role") != b"input":
            event.ignore()
            self.window().clear_drop_target_highlight(self)
            self.current_drag_highlight_item = None
            return

        # 2. Get target item (Output tree)
        target_item = self.itemAt(event.position().toPoint())
        if not target_item:
            event.ignore()
            self.window().clear_drop_target_highlight(self)
            self.current_drag_highlight_item = None
            return

        is_target_group = target_item.childCount() > 0
        target_ports = []
        if is_target_group:
            target_ports = self.window()._get_ports_in_group(target_item)
        else:
            target_port_name = target_item.data(0, Qt.ItemDataRole.UserRole)
            if target_port_name:
                target_ports = [target_port_name] # Treat single port as list

        if not target_ports: # No valid target port(s) found
            event.ignore()
            self.window().clear_drop_target_highlight(self)
            self.current_drag_highlight_item = None
            return

        # 3. Get source ports (Input)
        source_ports = mime_data.text().split('\n')
        # Filter out empty strings that might result from splitting
        source_ports = [port for port in source_ports if port]
        if not source_ports: # No valid source ports
             event.ignore()
             self.window().clear_drop_target_highlight(self)
             self.current_drag_highlight_item = None
             return

        # 4. Perform connection based on source and target types
        connection_made = False
        # Check for single port -> single port case
        if not is_group_drop and not is_port_list_drop and not is_target_group and len(source_ports) == 1 and len(target_ports) == 1:
             # Single Input Port -> Single Output Port
             output_name = target_ports[0]
             input_name = source_ports[0]
             print(f"Connecting single: {output_name} -> {input_name}")
             self.window().make_connection(output_name, input_name)
             connection_made = True
        # Check for cases involving groups or multiple ports
        elif (is_group_drop or is_port_list_drop or is_target_group):
             # Use make_multiple_connections for Group->Port, Port->Group, Group->Group, List->Port, List->Group
             print(f"Connecting multiple/group: Outputs={target_ports}, Inputs={source_ports}")
             self.window().make_multiple_connections(target_ports, source_ports)
             connection_made = True
        else:
             # This case might occur if logic above is flawed, or unexpected drop type
             print(f"Warning: Unhandled drop scenario in DragPortTreeWidget. Outputs={target_ports}, Inputs={source_ports}")
             event.ignore()


        # 5. Finalize
        if connection_made:
            event.acceptProposedAction()
        else:
            # This case should ideally not be reached if source/target ports are valid
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
        """Start drag operation with port name or group data"""
        selected_items = self.selectedItems()
        if not selected_items:
            return

        # Filter out group items if multiple items are selected
        port_items = [item for item in selected_items if item.childCount() == 0]
        group_items = [item for item in selected_items if item.childCount() > 0]

        mime_data = QMimeData()
        drag_text = ""

        if len(port_items) > 1:
            # Dragging multiple ports
            port_names = [item.data(0, Qt.ItemDataRole.UserRole) for item in port_items if item.data(0, Qt.ItemDataRole.UserRole)]
            if not port_names: return # No valid ports selected

            mime_data.setData("application/x-port-list", b"true") # Indicate multiple ports
            mime_data.setData("application/x-port-role", b"input") # Role is input
            mime_data.setText('\n'.join(port_names)) # Store port list
            drag_text = f"{len(port_names)} Input Ports" # Text for pixmap

        elif len(port_items) == 1 and not group_items:
            # Dragging a single port (original logic)
            item = port_items[0]
            port_name = item.data(0, Qt.ItemDataRole.UserRole)
            if not port_name: return # Don't drag invalid items

            mime_data.setData("application/x-port-role", b"input") # Role is input
            mime_data.setText(port_name)
            drag_text = item.text(0) # Use displayed text for pixmap

        elif len(group_items) == 1 and not port_items:
            # Dragging a single group (original logic)
            item = group_items[0]
            group_name = item.text(0)
            port_list = self.window()._get_ports_in_group(item)
            if not port_list: return # Don't drag empty groups

            mime_data.setData("application/x-port-group", b"true")
            mime_data.setData("application/x-port-role", b"input") # Role is input for this tree
            mime_data.setText('\n'.join(port_list)) # Store port list as newline-separated text
            drag_text = group_name # Text for pixmap

        else:
            # Invalid selection for dragging (e.g., mixed ports and groups, or nothing valid)
            return

        drag = QDrag(self)
        drag.setMimeData(mime_data)

        # Add visual feedback (using drag_text)
        # Create a generic pixmap for drag feedback
        font_metrics = QFontMetrics(self.font())
        text_width = font_metrics.horizontalAdvance(drag_text) + 10 # Add padding
        pixmap_width = max(70, text_width) # Ensure minimum width
        pixmap = QPixmap(pixmap_width, 20)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setPen(self.palette().color(QPalette.ColorRole.Text))
        # Use ElideRight if text is too long for the pixmap
        elided_text = font_metrics.elidedText(drag_text, Qt.TextElideMode.ElideRight, pixmap_width)
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, elided_text)
        painter.end()

        drag.setPixmap(pixmap)
        drag.setHotSpot(QPoint(pixmap.width() // 2, pixmap.height() // 2))

        result = drag.exec(Qt.DropAction.CopyAction)
        self.initialSelection = None # Clear selection after drag finishes

    def dragEnterEvent(self, event):
        """Handle drag enter events to determine if drop should be accepted"""
        mime_data = event.mimeData()
        is_port_drop = mime_data.hasFormat("application/x-port-role") and not mime_data.hasFormat("application/x-port-list") # Single port
        is_port_list_drop = mime_data.hasFormat("application/x-port-list") # Multiple ports
        is_group_drop = mime_data.hasFormat("application/x-port-group")

        # Accept if it's a single port, a list of ports, or a group, AND the role is output
        if (is_port_drop or is_port_list_drop or is_group_drop):
            # Role is always present for both port and group drags
            role = mime_data.data("application/x-port-role")
            if role == b"output":  # Only accept output ports/groups for drops on input tree
                event.acceptProposedAction()
                return

        event.ignore()

    def dragMoveEvent(self, event):
        """Handle drag move events for visual feedback, supporting ports and groups."""
        mime_data = event.mimeData()
        is_port_drag = mime_data.hasFormat("application/x-port-role") and not mime_data.hasFormat("application/x-port-list") # Single port
        is_port_list_drag = mime_data.hasFormat("application/x-port-list") # Multiple ports
        is_group_drag = mime_data.hasFormat("application/x-port-group")

        # 1. Check if it's a valid drag type we handle (Output role)
        if not (is_port_drag or is_port_list_drag or is_group_drag) or mime_data.data("application/x-port-role") != b"output":
            event.ignore()
            # Clear highlight if needed
            if self.current_drag_highlight_item:
                self.window().clear_drop_target_highlight(self)
                self.current_drag_highlight_item = None
            return

        # 2. Get item under cursor (Target item in Input tree)
        target_item = self.itemAt(event.position().toPoint())

        # 3. Determine if the target item is a valid drop target for the current drag source
        # Now, any target (port or group) is valid if the source is an Output port/group/list
        is_valid_target = bool(target_item)

        # 4. Handle highlighting and accepting/ignoring
        if is_valid_target:
            if target_item != self.current_drag_highlight_item:
                self.window().clear_drop_target_highlight(self)
                self.window().highlight_drop_target_item(self, target_item) # Highlight the valid target
                self.current_drag_highlight_item = target_item
            event.acceptProposedAction() # Accept move over valid target
        else:
            # Invalid target or no item under cursor
            if self.current_drag_highlight_item: # Clear highlight if there was one
                self.window().clear_drop_target_highlight(self)
                self.current_drag_highlight_item = None
            event.ignore() # Ignore move over invalid target

    def dropEvent(self, event):
        """Handle drop events to create connections for ports or groups."""
        mime_data = event.mimeData()
        is_port_drop = mime_data.hasFormat("application/x-port-role") and not mime_data.hasFormat("application/x-port-list") # Single port
        is_port_list_drop = mime_data.hasFormat("application/x-port-list") # Multiple ports
        is_group_drop = mime_data.hasFormat("application/x-port-group")

        # 1. Check validity (Source must be Output)
        if not (is_port_drop or is_port_list_drop or is_group_drop) or mime_data.data("application/x-port-role") != b"output":
            event.ignore()
            self.window().clear_drop_target_highlight(self)
            self.current_drag_highlight_item = None
            return

        # 2. Get target item (Input tree)
        target_item = self.itemAt(event.position().toPoint())
        if not target_item:
            event.ignore()
            self.window().clear_drop_target_highlight(self)
            self.current_drag_highlight_item = None
            return

        is_target_group = target_item.childCount() > 0
        target_ports = []
        if is_target_group:
            target_ports = self.window()._get_ports_in_group(target_item)
        else:
            target_port_name = target_item.data(0, Qt.ItemDataRole.UserRole)
            if target_port_name:
                target_ports = [target_port_name] # Treat single port as list

        if not target_ports: # No valid target port(s) found
            event.ignore()
            self.window().clear_drop_target_highlight(self)
            self.current_drag_highlight_item = None
            return

        # 3. Get source ports (Output)
        source_ports = mime_data.text().split('\n')
        # Filter out empty strings that might result from splitting
        source_ports = [port for port in source_ports if port]
        if not source_ports: # No valid source ports
             event.ignore()
             self.window().clear_drop_target_highlight(self)
             self.current_drag_highlight_item = None
             return

        # 4. Perform connection based on source and target types
        connection_made = False
        # Check for single port -> single port case
        if not is_group_drop and not is_port_list_drop and not is_target_group and len(source_ports) == 1 and len(target_ports) == 1:
             # Single Output Port -> Single Input Port
             output_name = source_ports[0]
             input_name = target_ports[0]
             print(f"Connecting single: {output_name} -> {input_name}")
             self.window().make_connection(output_name, input_name)
             connection_made = True
        # Check for cases involving groups or multiple ports
        elif (is_group_drop or is_port_list_drop or is_target_group):
             # Use make_multiple_connections for Group->Port, Port->Group, Group->Group, List->Port, List->Group
             print(f"Connecting multiple/group: Outputs={source_ports}, Inputs={target_ports}")
             self.window().make_multiple_connections(source_ports, target_ports)
             connection_made = True
        else:
             # This case might occur if logic above is flawed, or unexpected drop type
             print(f"Warning: Unhandled drop scenario in DropPortTreeWidget. Outputs={source_ports}, Inputs={target_ports}")
             event.ignore()

        # 5. Finalize
        if connection_made:
            event.acceptProposedAction()
        else:
            # This case should ideally not be reached if source/target ports are valid
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

        # Latency test variables
        self.latency_process = None
        self.latency_values = []
        self.latency_timer = QTimer()
        self.latency_waiting_for_connection = False # Flag to wait for connection
        # Store selected physical port aliases for latency test
        self.latency_selected_input_alias = None
        self.latency_selected_output_alias = None

        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        self.setCentralWidget(main_widget)
        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)

        self.audio_tab_widget = QWidget()
        self.midi_tab_widget = QWidget()
        self.pwtop_tab_widget = QWidget()
        self.latency_tab_widget = QWidget() # Added Latency Tab Widget

        self.setup_port_tab(self.audio_tab_widget, "Audio", 'audio')
        self.setup_port_tab(self.midi_tab_widget, "MIDI", 'midi')
        self.setup_pwtop_tab(self.pwtop_tab_widget)
        self.setup_latency_tab(self.latency_tab_widget) # Added call to setup latency tab

        self.tab_widget.addTab(self.audio_tab_widget, "Audio")
        self.tab_widget.addTab(self.midi_tab_widget, "MIDI")
        self.tab_widget.addTab(self.pwtop_tab_widget, "pw-top")
        self.tab_widget.addTab(self.latency_tab_widget, "Latency Test") # Added Latency Tab
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
        # pw-top process will be started when the tab is selected
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

    # --- Latency Test Methods ---

    def run_latency_test(self):
        """Starts the jack_delay process and timer."""
        if self.latency_process is not None and self.latency_process.state() != QProcess.ProcessState.NotRunning:
            self.latency_results_text.append("Test already in progress.")
            return

        # Refresh combo boxes with latest ports
        self._populate_latency_combos()

        self.latency_run_button.setEnabled(False)
        self.latency_stop_button.setEnabled(True) # Enable Stop button
        self.latency_results_text.clear() # Clear previous results/messages

        if self.latency_raw_output_checkbox.isChecked():
             self.latency_results_text.setText("Starting latency test (Raw Output)...\n"
                                               "Select ports if not already selected.\n"
                                               "Attempting auto-connection...\n")
        else:
             self.latency_results_text.setText("Starting latency test (Average)...\n"
                                               "Select ports if not already selected.\n"
                                               "Attempting auto-connection...\n"
                                               "Waiting for measurement signal...\n") # Updated message

        self.latency_values = []
        # Only wait for connection signal if NOT showing raw output
        self.latency_waiting_for_connection = not self.latency_raw_output_checkbox.isChecked()

        self.latency_process = QProcess()
        self.latency_process.readyReadStandardOutput.connect(self.handle_latency_output)
        self.latency_process.finished.connect(self.handle_latency_finished)
        self.latency_process.errorOccurred.connect(self.handle_latency_error)

        # Determine command based on environment
        if self.flatpak_env:
            program = "flatpak-spawn"
            arguments = ["--host", "jack_delay"]
        else:
            # Try jack_delay first, then jack_iodelay as fallback
            program = shutil.which("jack_delay")
            if program is None:
                program = shutil.which("jack_iodelay")

            # If neither is found, show error and exit
            if program is None:
                 self.latency_results_text.setText("Error: Neither 'jack_delay' nor 'jack_iodelay' found.\n"
                                                   "Depending on your distribution, install jack-delay, jack_delay or jack-example-tools (jack_iodelay).")
                 self.latency_run_button.setEnabled(True)  # Re-enable run button
                 self.latency_stop_button.setEnabled(False) # Ensure stop is disabled
                 self.latency_process = None # Clear the process object
                 return # Stop execution

            arguments = []

        self.latency_process.setProgram(program) # Use the found program path
        self.latency_process.setArguments(arguments)
        self.latency_process.start() # Start the process
        # Connection attempt is now triggered by _on_port_registered when jack_delay ports appear.

    def handle_latency_output(self):
        """Handles output from the jack_delay process."""
        if self.latency_process is None:
            return

        data = self.latency_process.readAllStandardOutput().data().decode()

        if self.latency_raw_output_checkbox.isChecked():
            # Raw output mode: Append data directly
            self.latency_results_text.moveCursor(QTextCursor.MoveOperation.End)
            self.latency_results_text.insertPlainText(data)
            self.latency_results_text.moveCursor(QTextCursor.MoveOperation.End)
        else:
            # Average calculation mode (original logic)
            # Check if we are waiting for the connection signal
            if self.latency_waiting_for_connection:
                # Check if any line contains a latency measurement
                if re.search(r'\d+\.\d+\s+ms', data):
                    self.latency_waiting_for_connection = False
                    self.latency_results_text.setText("Connection detected. Running test...") # Changed message
                    # Start the timer now
                    self.latency_timer.setSingleShot(True)
                    self.latency_timer.timeout.connect(self.stop_latency_test)
                    self.latency_timer.start(10000) # 10 seconds

            # If not waiting (or connection just detected), parse for values
            if not self.latency_waiting_for_connection:
                for line in data.splitlines():
                    # Updated regex to capture both frames and ms
                    match = re.search(r'(\d+\.\d+)\s+frames\s+(\d+\.\d+)\s+ms', line)
                    if match:
                        try:
                            latency_frames = float(match.group(1))
                            latency_ms = float(match.group(2))
                            # Store both values as a tuple
                            self.latency_values.append((latency_frames, latency_ms))
                        except ValueError:
                            pass # Ignore lines that don't parse correctly
    def stop_latency_test(self):
        """Stops the jack_delay process."""
        if self.latency_timer.isActive():
            self.latency_timer.stop() # Stop timer if called manually before timeout

        if self.latency_process is not None and self.latency_process.state() != QProcess.ProcessState.NotRunning:
            self.latency_results_text.append("\nStopping test...")
            self.latency_process.terminate()
            # Give it a moment to terminate gracefully before potentially killing
            if not self.latency_process.waitForFinished(500):
                self.latency_process.kill()
                self.latency_process.waitForFinished() # Wait for kill confirmation

            self.latency_waiting_for_connection = False # Reset flag

    def handle_latency_finished(self, exit_code, exit_status):
        """Handles the jack_delay process finishing."""
        # Clear previous text before showing final result
        self.latency_results_text.clear()

        if self.latency_raw_output_checkbox.isChecked():
            # If raw output was shown, just indicate stop
            self.latency_results_text.setText("Measurement stopped.")
        elif self.latency_values:
            # Calculate average for frames and ms separately (only if not raw output)
            total_frames = sum(val[0] for val in self.latency_values)
            total_ms = sum(val[1] for val in self.latency_values)
            count = len(self.latency_values)
            average_frames = total_frames / count
            average_ms = total_ms / count
            # Display both average latencies
            self.latency_results_text.setText(f"Round-trip latency (average): {average_frames:.3f} frames / {average_ms:.3f} ms")
        else:
            # Check if the process exited normally but produced no values
            if exit_status == QProcess.ExitStatus.NormalExit and exit_code == 0:
                 # Display a clear error message
                 self.latency_results_text.setText("No valid latency readings obtained. Check connections.")
            elif exit_status == QProcess.ExitStatus.CrashExit:
                 self.latency_results_text.setText("Measurement stopped.")
            # Error message handled by handle_latency_error if exit code != 0 and no values were found
            elif exit_code != 0:
                 # If an error occurred (handled by handle_latency_error),
                 # ensure some message is shown if handle_latency_error didn't set one.
                 if not self.latency_results_text.toPlainText():
                     self.latency_results_text.setText(f"Test failed (Exit code: {exit_code}). Check connections.")
            else: # Should not happen often, but catch other cases
                 self.latency_results_text.setText("Test finished without valid readings.")


        self.latency_waiting_for_connection = False # Reset flag
        self.latency_run_button.setEnabled(True)
        self.latency_stop_button.setEnabled(False) # Disable Stop button
        self.latency_process = None # Clear the process reference

    def handle_latency_error(self, error):
        """Handles errors occurring during the jack_delay process execution."""
        error_string = self.latency_process.errorString() if self.latency_process else "Unknown error"
        self.latency_results_text.append(f"\nError running jack_delay: {error} - {error_string}")

        # Ensure timer and process are stopped/cleaned up
        if self.latency_timer.isActive():
            self.latency_timer.stop()
        if self.latency_process is not None:
            # Ensure process is terminated if it hasn't finished yet
            if self.latency_process.state() != QProcess.ProcessState.NotRunning:
                self.latency_process.kill()
                self.latency_process.waitForFinished()
            self.latency_process = None

        self.latency_waiting_for_connection = False # Reset flag
        self.latency_run_button.setEnabled(True)
        self.latency_stop_button.setEnabled(False) # Disable Stop button on error

    # --- End Latency Test Methods ---

    def update_pwtop_output(self):
        """Handle pw-top output updates"""
        if self.pw_process is not None:
            self.handle_pwtop_output()

    def setup_latency_tab(self, tab_widget):
        """Set up the Latency Test tab"""
        layout = QVBoxLayout(tab_widget)

        # Instructions Label

        instructions_text = (
            "<b>Instructions:</b><br><br>"
            "1. Ensure 'jack_delay', 'jack-delay' or 'jack_iodelay' (via 'jack-example-tools') is installed.<br>"
            "2. Physically connect an output and input of your audio interface using a cable (loopback).<br>"
            "3. Select the corresponding Input (Capture) and Output (Playback) ports using the dropdowns below.<br>"
            "4. Click 'Start Measurement'. The selected ports will be automatically connected to jack_delay.<br>"
            "(you can click 'Start Measurement' first and then try different ports)<br>"
            "5. <b><font color='orange'>Warning:</font></b> Start with low volume/gain levels on your interface "
            "to avoid potential damage from the test signal.<br><br>"
            "After the signal is detected, the average measured round-trip latency will be shown after 10 seconds.<br><br><br><br><br>"
        )

        instructions_label = QLabel(instructions_text)
        instructions_label.setWordWrap(True)
        instructions_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        # Increase font size for instructions
        instructions_label.setStyleSheet(f"color: {self.text_color.name()}; font-size: 11pt;")
        layout.addWidget(instructions_label)

        # --- Combo Boxes for Port Selection ---
        self.latency_input_combo = QComboBox()
        self.latency_input_combo.setPlaceholderText("Select Input (Capture)...")
        self.latency_input_combo.setStyleSheet(self.list_stylesheet()) # Reuse list style

        self.latency_output_combo = QComboBox()
        self.latency_output_combo.setPlaceholderText("Select Output (Playback)...")
        self.latency_output_combo.setStyleSheet(self.list_stylesheet()) # Reuse list style

        # --- Refresh Button ---
        self.latency_refresh_button = QPushButton("Refresh Ports")
        self.latency_refresh_button.setStyleSheet(self.button_stylesheet())
        self.latency_refresh_button.clicked.connect(self._populate_latency_combos) # Connect to refresh method
        # --- End Refresh Button ---

        # Input Row
        input_combo_layout = QHBoxLayout()
        input_combo_layout.addWidget(QLabel("Input  Port:  "))
        input_combo_layout.addWidget(self.latency_input_combo, 1) # Add stretch factor
        input_combo_layout.addStretch(1) # Add spacer to limit dropdown width
        layout.addLayout(input_combo_layout)

        # Output Row
        output_combo_layout = QHBoxLayout()
        output_combo_layout.addWidget(QLabel("Output Port:"))
        output_combo_layout.addWidget(self.latency_output_combo, 1) # Add stretch factor
        output_combo_layout.addStretch(1) # Add spacer to limit dropdown width
        layout.addLayout(output_combo_layout)

        # Add Refresh button separately below the dropdowns
        refresh_button_layout = QHBoxLayout()
        refresh_button_layout.addStretch(1) # Push button to the right
        refresh_button_layout.addWidget(self.latency_refresh_button)
        layout.addLayout(refresh_button_layout)
        # --- End Combo Boxes ---


        # Buttons Layout
        button_layout = QHBoxLayout()
        self.latency_run_button = QPushButton('Start measurement')
        self.latency_run_button.setStyleSheet(self.button_stylesheet())
        self.latency_run_button.clicked.connect(self.run_latency_test)

        self.latency_stop_button = QPushButton('Stop')
        self.latency_stop_button.setStyleSheet(self.button_stylesheet())
        self.latency_stop_button.clicked.connect(self.stop_latency_test)
        self.latency_stop_button.setEnabled(False) # Initially disabled

        button_layout.addWidget(self.latency_run_button)
        button_layout.addWidget(self.latency_stop_button)
        layout.addLayout(button_layout) # Add the horizontal layout for buttons

        # Raw Output Toggle Checkbox
        self.latency_raw_output_checkbox = QCheckBox("Show Raw Output (Continuous)")
        self.latency_raw_output_checkbox.setStyleSheet(f"color: {self.text_color.name()};") # Style checkbox text
        layout.addWidget(self.latency_raw_output_checkbox) # Add checkbox below buttons

        # Results Text Edit
        self.latency_results_text = QTextEdit()
        self.latency_results_text.setReadOnly(True)
        # Increase font size for results text
        self.latency_results_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: {self.background_color.name()};
                color: {self.text_color.name()};
                font-family: monospace;
                font-size: 14pt;
            }}
        """)
        self.latency_results_text.setText("Ready to test.")
        layout.addWidget(self.latency_results_text, 1) # Add stretch factor

        # Populate combo boxes
        self._populate_latency_combos()

        # Connect signals
        self.latency_input_combo.currentIndexChanged.connect(self._on_latency_input_selected)
        self.latency_output_combo.currentIndexChanged.connect(self._on_latency_output_selected)

    def _populate_latency_combos(self):
        """Populates the latency test combo boxes using python-jack."""
        capture_ports = [] # Physical capture devices (JACK outputs)
        playback_ports = [] # Physical playback devices (JACK inputs)
        try:
            # Get physical capture ports (System Output -> JACK Input)
            jack_capture_ports = self.client.get_ports(is_physical=True, is_audio=True, is_output=True)
            capture_ports = sorted([port.name for port in jack_capture_ports])

            # Get physical playback ports (System Input <- JACK Output)
            jack_playback_ports = self.client.get_ports(is_physical=True, is_audio=True, is_input=True)
            playback_ports = sorted([port.name for port in jack_playback_ports])

        except jack.JackError as e:
            print(f"Error getting physical JACK ports: {e}")
            # Optionally display an error in the UI

        # Block signals while populating to avoid triggering handlers prematurely
        self.latency_input_combo.blockSignals(True)
        self.latency_output_combo.blockSignals(True)

        # Clear existing items first, keeping placeholder
        self.latency_input_combo.clear()
        self.latency_output_combo.clear()
        self.latency_input_combo.addItem("Select Physical Input (Capture)...", None) # Add placeholder back
        self.latency_output_combo.addItem("Select Physical Output (Playback)...", None) # Add placeholder back

        # Populate Input Combo (Capture Ports - JACK Outputs)
        for port_name in capture_ports:
            self.latency_input_combo.addItem(port_name, port_name) # Use name for display and data

        # Populate Output Combo (Playback Ports - JACK Inputs)
        for port_name in playback_ports:
            self.latency_output_combo.addItem(port_name, port_name) # Use name for display and data

        # Restore previous selection if port names still exist
        if self.latency_selected_input_alias:
            index = self.latency_input_combo.findData(self.latency_selected_input_alias)
            if index != -1:
                self.latency_input_combo.setCurrentIndex(index)
        if self.latency_selected_output_alias:
            index = self.latency_output_combo.findData(self.latency_selected_output_alias)
            if index != -1:
                self.latency_output_combo.setCurrentIndex(index)

        # Unblock signals
        self.latency_input_combo.blockSignals(False)
        self.latency_output_combo.blockSignals(False)


    def _on_latency_input_selected(self, index):
        """Stores the selected physical input port alias."""
        self.latency_selected_input_alias = self.latency_input_combo.itemData(index)
        # Attempt connection if output is also selected and test is running
        self._attempt_latency_auto_connection()

    def _on_latency_output_selected(self, index):
        """Stores the selected physical output port alias."""
        self.latency_selected_output_alias = self.latency_output_combo.itemData(index)
        # Attempt connection if input is also selected and test is running
        self._attempt_latency_auto_connection()

    def _attempt_latency_auto_connection(self):
        """Connects selected physical ports to jack_delay if ports are selected."""
        # Only connect if both an input and output alias have been selected from the dropdowns.
        # The call to this function is now triggered by jack_delay port registration.
        if (self.latency_selected_input_alias and
            self.latency_selected_output_alias):

            # Pipewire 'in' direction (our output_ports list) connects to jack_delay:out
            # Pipewire 'out' direction (our input_ports list) connects to jack_delay:in
            output_to_connect = self.latency_selected_output_alias # This is the physical playback port alias
            input_to_connect = self.latency_selected_input_alias   # This is the physical capture port alias

            print(f"Attempting auto-connection: jack_delay:out -> {output_to_connect}")
            print(f"Attempting auto-connection: {input_to_connect} -> jack_delay:in")

            # Use the existing connection methods (ensure jack_delay ports exist first)
            # We might need a small delay or check if jack_delay ports are ready.
            # For now, let's assume they appear quickly after process start.
            try:
                # Connect jack_delay output to the selected physical playback port
                # Ensure the target port exists before connecting
                if any(p.name == output_to_connect for p in self.client.get_ports(is_input=True, is_audio=True)):
                     self.make_connection("jack_delay:out", output_to_connect)
                else:
                     print(f"Warning: Target output port '{output_to_connect}' not found.")

                # Connect the selected physical capture port to jack_delay input
                # Ensure the target port exists before connecting
                if any(p.name == input_to_connect for p in self.client.get_ports(is_output=True, is_audio=True)):
                    self.make_connection(input_to_connect, "jack_delay:in")
                else:
                    print(f"Warning: Target input port '{input_to_connect}' not found.")

                self.latency_results_text.append("\nTry diffrent ports if you're seeing this message after clicking 'Start measurement button")
                # Refresh the audio tab view to show the new connections
                if self.port_type == 'audio':
                    self.refresh_ports()

            except jack.JackError as e:
                 # Catch specific Jack errors if needed, e.g., port not found
                 print(f"Error during latency auto-connection (JackError): {e}")
                 self.latency_results_text.append(f"\nError auto-connecting (JACK): {e}")
            except Exception as e:
                print(f"Error during latency auto-connection: {e}")
                self.latency_results_text.append(f"\nError auto-connecting: {e}")

    # Removed _get_physical_audio_ports method as we now use python-jack directly

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
        # Stop pw-top if switching away from it (index is the *new* index)
        if index != 2 and hasattr(self, 'pw_process') and self.pw_process is not None:
            self.stop_pwtop_process()
        
        # Configure based on the new tab index
        if index < 2:  # Audio or MIDI tabs
            self.port_type = 'audio' if index == 0 else 'midi'
            self.apply_collapse_state_to_all_trees()
            self.refresh_visualizations()
            self.show_bottom_controls(True) # Show controls
        elif index == 2:  # pw-top tab
            # Start pw-top process only when switching to this tab
            if self.pw_process is None or self.pw_process.state() == QProcess.ProcessState.NotRunning:
                self.start_pwtop_process()
            self.show_bottom_controls(False) # Hide controls
        elif index == 3: # jack_delay tab
            # No specific process to start here, just hide controls
            self.show_bottom_controls(False) # Hide controls

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
        

        # Check if this is a jack_delay port registration, and if so, attempt auto-connection
        if port_name == "jack_delay:in" or port_name == "jack_delay:out":
            print(f"Detected registration of {port_name}, attempting latency auto-connection...")
            # Use QTimer.singleShot to slightly delay the connection attempt,
            # ensuring both jack_delay ports might be ready.
            QTimer.singleShot(50, self._attempt_latency_auto_connection) # 50ms delay

        self.refresh_ports()


    def _on_port_unregistered(self, port_name: str, is_input: bool):
        """Handle port unregistration events in the Qt main thread"""
        if not self.callbacks_enabled:
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

    def _get_selected_item_info(self, tree_widget):
        """Gets information about the currently selected item (port or group)."""
        if not hasattr(tree_widget, 'currentItem'):
            return None, None # Not a valid tree
        item = tree_widget.currentItem()
        if not item:
            return None, None # Nothing selected

        is_group = item.childCount() > 0
        if is_group:
            return item.text(0), True # Return group name and True
        else:
            port_name = item.data(0, Qt.ItemDataRole.UserRole)
            return port_name, False # Return port name and False

    def _restore_selection(self, tree_widget, selection_info):
        """Restores selection based on saved info (group name or port name)."""
        if not selection_info or not hasattr(tree_widget, 'port_items'):
            return

        name_or_text, is_group = selection_info
        if name_or_text is None:
            return

        item_to_select = None
        if is_group:
            # Find group item by text
            for i in range(tree_widget.topLevelItemCount()):
                group_item = tree_widget.topLevelItem(i)
                if group_item.text(0) == name_or_text:
                    item_to_select = group_item
                    break
        else:
            # Find port item by port name (UserRole data)
            item_to_select = tree_widget.port_items.get(name_or_text)

        if item_to_select and not item_to_select.isHidden():
            tree_widget.setCurrentItem(item_to_select)

    def refresh_ports(self):
        # 1. Determine current context (trees, filters, type)
        if self.port_type == 'audio':
            input_tree = self.input_tree
            output_tree = self.output_tree
            update_visuals = self.update_connections
            clear_highlights = self.clear_highlights
            update_buttons = self.update_connection_buttons
            is_midi = False
        elif self.port_type == 'midi':
            input_tree = self.midi_input_tree
            output_tree = self.midi_output_tree
            update_visuals = self.update_midi_connections
            clear_highlights = self.clear_midi_highlights
            update_buttons = self.update_midi_connection_buttons
            is_midi = True
        else:
            return # Should not happen

        # Use shared filter edits
        current_input_filter = self.input_filter_edit.text() if hasattr(self, 'input_filter_edit') else ""
        current_output_filter = self.output_filter_edit.text() if hasattr(self, 'output_filter_edit') else ""

        # 2. Save current selection (port or group)
        selected_input_info = self._get_selected_item_info(input_tree)
        selected_output_info = self._get_selected_item_info(output_tree)

        # 3. Clear and repopulate trees
        input_tree.clear()
        output_tree.clear()
        input_ports, output_ports = self._get_ports(is_midi=is_midi)
        for port in input_ports:
            input_tree.addPort(port)
        for port in output_ports:
            output_tree.addPort(port)

        # 4. Re-apply filter
        self.filter_ports(input_tree, current_input_filter)
        self.filter_ports(output_tree, current_output_filter)

        # 5. Restore selection
        self._restore_selection(input_tree, selected_input_info)
        self._restore_selection(output_tree, selected_output_info)

        # 6. Update visuals and button states
        update_visuals()
        clear_highlights() # Clear old highlights before applying new ones
        update_buttons()

        # 7. Re-apply highlights based on the *restored* selection
        restored_input_item = input_tree.currentItem()
        restored_output_item = output_tree.currentItem()

        # Highlight selected item itself (port or group)
        if restored_input_item:
            if restored_input_item.childCount() == 0: # Port
                 port_name = restored_input_item.data(0, Qt.ItemDataRole.UserRole)
                 self._highlight_tree_item(input_tree, port_name) # Highlight selected port
            # No specific highlight for the selected group itself, only connected ones

        if restored_output_item:
             if restored_output_item.childCount() == 0: # Port
                 port_name = restored_output_item.data(0, Qt.ItemDataRole.UserRole)
                 self._highlight_tree_item(output_tree, port_name) # Highlight selected port
             # No specific highlight for the selected group itself, only connected ones


        # Highlight connected items/groups
        if restored_input_item:
            if restored_input_item.childCount() > 0: # Group selected
                self._highlight_connected_output_groups_for_input_group(restored_input_item, is_midi)
            else: # Port selected
                port_name = restored_input_item.data(0, Qt.ItemDataRole.UserRole)
                if port_name: # Ensure port_name is valid
                    self._highlight_connected_outputs_for_input(port_name, is_midi)


        if restored_output_item:
            if restored_output_item.childCount() > 0: # Group selected
                self._highlight_connected_input_groups_for_output_group(restored_output_item, is_midi)
            else: # Port selected
                port_name = restored_output_item.data(0, Qt.ItemDataRole.UserRole)
                if port_name: # Ensure port_name is valid
                    self._highlight_connected_inputs_for_output(port_name, is_midi)


        # 8. Maintain collapse state if needed
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
            # Get input port objects
            input_port_objects = self.client.get_ports(is_input=True, is_midi=is_midi)

            # Get output port objects
            output_port_objects = self.client.get_ports(is_output=True, is_midi=is_midi)

            # Explicitly filter for the Audio tab (is_midi=False)
            # Ensure only ports reported as non-MIDI by the port object itself are included.
            if not is_midi:
                input_port_objects = [p for p in input_port_objects if p is not None and not p.is_midi]
                output_port_objects = [p for p in output_port_objects if p is not None and not p.is_midi]
            else:
                # For MIDI tab, just ensure ports are not None
                input_port_objects = [p for p in input_port_objects if p is not None]
                output_port_objects = [p for p in output_port_objects if p is not None]


            # Extract names from the filtered objects
            input_ports = [p.name for p in input_port_objects]
            output_ports = [p.name for p in output_port_objects]

            # Sort the names
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

    # Add this new method to the JackConnectionManager class
    def make_multiple_connections(self, outputs, inputs):
        """Connects multiple output ports to multiple input ports,
           handling group/list-to-port and port-to-group/list scenarios.
           Determines if it's audio or MIDI based on the current tab."""
        if not outputs or not inputs:
            print("Warning: make_multiple_connections called with empty outputs or inputs.")
            return

        # Ensure inputs are lists for consistent handling
        output_list = outputs if isinstance(outputs, list) else [outputs]
        input_list = inputs if isinstance(inputs, list) else [inputs]

        if not output_list or not input_list:
             print(f"Warning: make_multiple_connections called with empty lists after ensuring list type: outputs={output_list}, inputs={input_list}")
             return

        # Determine if MIDI or Audio based on the current tab
        is_midi = self.tab_widget.currentIndex() == 1 # Assuming MIDI is tab index 1
        # Use _port_operation directly as it handles history and updates
        operation_type = 'connect'

        num_outputs = len(output_list)
        num_inputs = len(input_list)
        made_connection_attempt = False

        print(f"make_multiple_connections: {num_outputs} outputs, {num_inputs} inputs. MIDI: {is_midi}")

        if num_outputs > 1 and num_inputs == 1:
            # Group/List to Port: Connect all outputs to the single input
            single_input = input_list[0]
            print(f"  Scenario: Group/List ({num_outputs}) -> Port ({single_input})")
            for output_name in output_list:
                try:
                    self._port_operation(operation_type, output_name, single_input, is_midi)
                    made_connection_attempt = True
                except jack.JackError as e:
                    print(f"  Failed to connect {output_name} -> {single_input}: {e}")

        elif num_outputs == 1 and num_inputs > 1:
            # Port to Group/List: Connect the single output to all inputs
            single_output = output_list[0]
            print(f"  Scenario: Port ({single_output}) -> Group/List ({num_inputs})")
            for input_name in input_list:
                try:
                    self._port_operation(operation_type, single_output, input_name, is_midi)
                    made_connection_attempt = True
                except jack.JackError as e:
                    print(f"  Failed to connect {single_output} -> {input_name}: {e}")

        elif num_outputs > 1 and num_inputs > 1:
            # Group/List to Group/List: Use suffix matching then sequential matching (Restored Logic)
            print(f"  Scenario: Group/List ({num_outputs}) -> Group/List ({num_inputs}) - Applying suffix/sequential matching")

            # Define common suffixes for matching (copied from original logic)
            common_suffixes = [
               '_FL', '_FR', '_SL', '_SR', '_FC', '_LFE', '_RL', '_RR',
               '_L', '_R', '_1', '_2', '_3', '_4', '_5', '_6', '_7', '_8',
               'left', 'right', 'Left', 'Right'
            ]

            # Create copies to modify while iterating
            unmatched_outputs = list(output_list)
            unmatched_inputs = list(input_list)
            connections_made_in_group = [] # Track connections made in this block

            # First pass: match by exact suffixes
            for suffix in common_suffixes:
                outputs_with_suffix = [p for p in unmatched_outputs if p.endswith(suffix)]
                inputs_with_suffix = [p for p in unmatched_inputs if p.endswith(suffix)]

                # Pair up matching ports based on suffix
                pairs_to_connect = min(len(outputs_with_suffix), len(inputs_with_suffix))
                for i in range(pairs_to_connect):
                    out_p = outputs_with_suffix[i]
                    in_p = inputs_with_suffix[i]
                    try:
                        print(f"    Suffix Match ({suffix}): {out_p} -> {in_p}")
                        # Use _port_operation directly to handle history correctly for each pair
                        self._port_operation(operation_type, out_p, in_p, is_midi)
                        connections_made_in_group.append((out_p, in_p))
                        unmatched_outputs.remove(out_p)
                        unmatched_inputs.remove(in_p)
                        made_connection_attempt = True # Set the outer flag
                    except Exception as e:
                        print(f"      Connection failed: {e}")

            # Second pass: try to match remaining ports sequentially
            while unmatched_outputs and unmatched_inputs:
                out_p = unmatched_outputs[0]
                in_p = unmatched_inputs[0]
                try:
                    print(f"    Sequential Match: {out_p} -> {in_p}")
                    # Use _port_operation directly
                    self._port_operation(operation_type, out_p, in_p, is_midi)
                    connections_made_in_group.append((out_p, in_p))
                    made_connection_attempt = True # Set the outer flag
                except Exception as e:
                    print(f"      Connection failed: {e}")
                # Remove the matched ports regardless of success to avoid infinite loops on error
                unmatched_outputs.pop(0)
                unmatched_inputs.pop(0)

            print(f"  Group-to-group connection finished. Attempted {len(connections_made_in_group)} connections.")

        elif num_outputs == 1 and num_inputs == 1:
             # Single Port to Single Port
             single_output = output_list[0]
             single_input = input_list[0]
             print(f"  Scenario: Port ({single_output}) -> Port ({single_input})")
             try:
                 self._port_operation(operation_type, single_output, single_input, is_midi)
                 made_connection_attempt = True
             except jack.JackError as e:
                 print(f"  Failed to connect {single_output} -> {single_input}: {e}")
        else:
            # Should not happen if lists are not empty at the start
            print(f"Warning: Unexpected case in make_multiple_connections: {num_outputs} outputs, {num_inputs} inputs")


        if made_connection_attempt:
            print("Multiple connection process finished.")
            # self.refresh_visualizations() # _port_operation calls refresh_ports which calls update_connections
            # self.update_undo_redo_buttons() # _port_operation calls this
            pass # Updates are handled within _port_operation calls
    def make_group_connection(self, output_ports, input_ports):
       """
       Connects a group of output ports to a group of input ports,
       attempting to match common channel suffixes first.
       """
       print(f"Attempting group connection: {output_ports} -> {input_ports}")

       # Determine if it's MIDI based on port names (simple heuristic)
       is_midi = any('midi' in p.lower() for p in output_ports + input_ports)
       connection_func = self.make_midi_connection if is_midi else self.make_connection

       # --- Suffix-based matching ---
       common_suffixes = [
           '_FL', '_FR',  # Front Left/Right
           '_SL', '_SR',  # Surround Left/Right
           '_FC', '_LFE', # Center/Subwoofer
           '_RL', '_RR',  # Rear Left/Right
           '_L', '_R',    # Generic Left/Right
           '_1', '_2', '_3', '_4', '_5', '_6', '_7', '_8',  # Numbered channels
           'left', 'right',  # Alternative naming
           'Left', 'Right',
        #   '_FL-*', '_FR-*'
       ]

       # Create copies to modify while iterating
       unmatched_outputs = list(output_ports)
       unmatched_inputs = list(input_ports)
       connections_made = []

       # First pass: match by exact suffixes
       for suffix in common_suffixes:
           outputs_with_suffix = [p for p in unmatched_outputs if p.endswith(suffix)]
           inputs_with_suffix = [p for p in unmatched_inputs if p.endswith(suffix)]

           for out_p, in_p in zip(outputs_with_suffix, inputs_with_suffix):
               try:
                   print(f"  Suffix Match ({suffix}): {out_p} -> {in_p}")
                   connection_func(out_p, in_p)
                   connections_made.append((out_p, in_p))
                   unmatched_outputs.remove(out_p)
                   unmatched_inputs.remove(in_p)
               except Exception as e:
                   print(f"    Connection failed: {e}")

       # Second pass: try to match remaining ports in order
       # This handles cases where suffixes don't match exactly
       while unmatched_outputs and unmatched_inputs:
           out_p = unmatched_outputs[0]
           in_p = unmatched_inputs[0]
           try:
               print(f"  Sequential Match: {out_p} -> {in_p}")
               connection_func(out_p, in_p)
               connections_made.append((out_p, in_p))
           except Exception as e:
               print(f"    Connection failed: {e}")
           unmatched_outputs.pop(0)
           unmatched_inputs.pop(0)

       print(f"Group connection finished. Made {len(connections_made)} connections.")
       return len(connections_made) > 0

    def _get_ports_in_group(self, item):
        """Get all ports in a group or just the single port if it's a port item"""
        if not item:
            return []
        if item.childCount() == 0:  # It's a port item
            port_name = item.data(0, Qt.ItemDataRole.UserRole)
            return [port_name] if port_name else []
        else:  # It's a group item
            ports = []
            for i in range(item.childCount()):
                child = item.child(i)
                port_name = child.data(0, Qt.ItemDataRole.UserRole)
                if port_name:
                    ports.append(port_name)
            return ports

    def make_connection_selected(self):
        """Connects selected items. Uses pairwise logic for pure group selections,
           cross-product otherwise."""
        selected_input_items = self.input_tree.selectedItems()
        selected_output_items = self.output_tree.selectedItems()

        # Always use cross-product logic for button clicks.
        # Get all ports from selected items (handles both ports and groups).
        selected_inputs = self._get_ports_from_selected_items(self.input_tree)
        selected_outputs = self._get_ports_from_selected_items(self.output_tree)

        if not selected_inputs or not selected_outputs:
            print("Make Connection: Select at least one input and one output item (port or group).")
            return

        print(f"Making connections (button): Outputs={selected_outputs}, Inputs={selected_inputs}")
        # Use make_multiple_connections which handles the cross-product internally
        self.make_multiple_connections(selected_outputs, selected_inputs)

    def make_midi_connection_selected(self):
        """Connects selected MIDI items. Uses pairwise logic for pure group selections,
           cross-product otherwise."""
        selected_input_items = self.midi_input_tree.selectedItems()
        selected_output_items = self.midi_output_tree.selectedItems()

        # Always use cross-product logic for button clicks.
        # Get all ports from selected items (handles both ports and groups).
        selected_inputs = self._get_ports_from_selected_items(self.midi_input_tree)
        selected_outputs = self._get_ports_from_selected_items(self.midi_output_tree)

        if not selected_inputs or not selected_outputs:
            print("Make MIDI Connection: Select at least one input and one output item (port or group).")
            return

        print(f"Making MIDI connections (button): Outputs={selected_outputs}, Inputs={selected_inputs}")
        # Use make_multiple_connections which handles the cross-product internally
        self.make_multiple_connections(selected_outputs, selected_inputs)

    def break_group_connection(self, output_ports, input_ports):
        """Break all connections between two groups of ports"""
        is_midi = any('midi' in p.lower() for p in output_ports + input_ports)
        disconnect_func = self.break_midi_connection if is_midi else self.break_connection
        
        for output_port in output_ports:
            try:
                connections = self.client.get_all_connections(output_port)
                for connection in connections:
                    if connection.name in input_ports:
                        disconnect_func(output_port, connection.name)
            except jack.JackError as e:
                print(f"Error breaking connection from {output_port}: {e}")

    def break_connection_selected(self):
        """Disconnects all selected output ports from all selected input ports."""
        selected_inputs = self._get_ports_from_selected_items(self.input_tree)
        selected_outputs = self._get_ports_from_selected_items(self.output_tree)

        if not selected_inputs or not selected_outputs:
            print("Break Connection: Select at least one input and one output port.")
            return

        print(f"Breaking connections for: Outputs={selected_outputs}, Inputs={selected_inputs}")
        for out_port in selected_outputs:
            for in_port in selected_inputs:
                # We only need to attempt disconnection, Jack handles non-existent ones gracefully
                self.break_connection(out_port, in_port) # Use existing single disconnection method

    def break_midi_connection_selected(self):
        """Disconnects all selected MIDI output ports from all selected MIDI input ports."""
        selected_inputs = self._get_ports_from_selected_items(self.midi_input_tree)
        selected_outputs = self._get_ports_from_selected_items(self.midi_output_tree)

        if not selected_inputs or not selected_outputs:
            print("Break MIDI Connection: Select at least one input and one output MIDI port.")
            return

        print(f"Breaking MIDI connections for: Outputs={selected_outputs}, Inputs={selected_inputs}")
        for out_port in selected_outputs:
            for in_port in selected_inputs:
                # We only need to attempt disconnection, Jack handles non-existent ones gracefully
                self.break_midi_connection(out_port, in_port) # Use existing single MIDI disconnection method

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


    def disconnect_selected_groups(self, group_items):
        """Disconnects all connections for all ports within the selected group items."""
        ports_to_disconnect = set()

        for group_item in group_items:
            # Ensure it's actually a group item (has children)
            if group_item and group_item.childCount() > 0:
                for i in range(group_item.childCount()):
                    port_item = group_item.child(i)
                    port_name = port_item.data(0, Qt.ItemDataRole.UserRole)
                    if port_name:
                        ports_to_disconnect.add(port_name)

        if not ports_to_disconnect:
            # print("No ports found in selected groups to disconnect.") # Optional: logging
            return

        # print(f"Disconnecting ports from selected groups: {ports_to_disconnect}") # Optional: logging
        for port_name in ports_to_disconnect:
            # Use the existing disconnect_node logic which handles connections
            # and updates history/UI via break_connection/_port_operation
            self.disconnect_node(port_name)

        # No explicit refresh needed here as disconnect_node triggers updates


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
        """Handle selection in tree widgets for ports and groups, respecting Ctrl modifier."""

        # Check if Ctrl key is pressed during the click that triggered this handler
        ctrl_pressed = QGuiApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier

        if not ctrl_pressed:
            # --- Standard Click Behavior (No Ctrl) ---
            # 1. Clear previous highlights
            if is_midi:
                self.clear_midi_highlights()
            else:
                self.clear_highlights()

            # 2. Set the current item in the tree that was clicked
            #    (This implicitly clears other selections unless ExtendedSelection handles it,
            #     but since we called super().mousePressEvent, it should work)
            # clicked_tree.setCurrentItem(item) # Let the mousePressEvent handle selection setting

            # Highlight the clicked item itself
            port_name_or_group = item.data(0, Qt.ItemDataRole.UserRole) or item.text(0)
            if is_midi:
                 if clicked_tree == self.midi_input_tree: self.highlight_midi_input(port_name_or_group)
                 else: self.highlight_midi_output(port_name_or_group)
            else:
                 if clicked_tree == self.input_tree: self.highlight_input(port_name_or_group)
                 else: self.highlight_output(port_name_or_group)

        # --- Behavior for Both Ctrl+Click and Standard Click ---
        # 3. Handle highlighting of connected items based on the *currently clicked* item
        is_group_item = item.childCount() > 0

        if is_group_item:
            # Group item clicked - highlight connected groups and update buttons
            if is_midi:
                if clicked_tree == self.midi_input_tree:
                    self._highlight_connected_output_groups_for_input_group(item, is_midi)
                else: # Clicked on midi_output_tree
                    self._highlight_connected_input_groups_for_output_group(item, is_midi)
                self.update_midi_connection_buttons()
            else: # Audio
                if clicked_tree == self.input_tree:
                    self._highlight_connected_output_groups_for_input_group(item, is_midi)
                else: # Clicked on output_tree
                    self._highlight_connected_input_groups_for_output_group(item, is_midi)
                self.update_connection_buttons()
        else:
            # Port item clicked - perform highlighting and update buttons
            port_name = item.data(0, Qt.ItemDataRole.UserRole)
            if not port_name: return # Should not happen, but safety check

            if is_midi:
                if clicked_tree == self.midi_input_tree:
                    self.highlight_midi_input(port_name)
                    self._highlight_connected_outputs_for_input(port_name, is_midi)
                    self.update_midi_connection_buttons()
                else: # Clicked on midi_output_tree
                    self.highlight_midi_output(port_name)
                    self._highlight_connected_inputs_for_output(port_name, is_midi)
                    self.update_midi_connection_buttons()
            else: # Audio
                if clicked_tree == self.input_tree:
                    self.highlight_input(port_name)
                    self._highlight_connected_outputs_for_input(port_name, is_midi)
                    self.update_connection_buttons()
                else: # Clicked on output_tree
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

    def _highlight_connected_output_groups_for_input_group(self, input_group_item, is_midi):
        """Finds and highlights output groups connected to the selected input group."""
        input_ports = self._get_ports_in_group(input_group_item)
        if not input_ports: return

        output_tree = self.midi_output_tree if is_midi else self.output_tree
        highlight_func = self._highlight_group_item # Use the new group highlight function

        try:
            # Iterate through all output ports to find connections to any port in the input group
            output_port_objects = self.client.get_ports(is_output=True, is_midi=is_midi)
            connected_output_groups = set() # Store names of groups to highlight

            for output_port in output_port_objects:
                try:
                    # Check if output port exists before querying
                    if not any(p.name == output_port.name for p in self.client.get_ports(is_output=True, is_midi=is_midi)):
                        continue
                    connections = self.client.get_all_connections(output_port)
                    # Check if this output port connects to *any* port in the selected input group
                    if any(conn.name in input_ports for conn in connections):
                        # Find the group this output port belongs to
                        output_item = output_tree.port_items.get(output_port.name)
                        if output_item and output_item.parent():
                            connected_output_groups.add(output_item.parent().text(0))
                except jack.JackError:
                    continue # Ignore errors for individual ports

            # Highlight the identified groups
            for group_name in connected_output_groups:
                highlight_func(output_tree, group_name)

        except jack.JackError as e:
            print(f"Error highlighting connected output groups: {e}")

    def _highlight_connected_input_groups_for_output_group(self, output_group_item, is_midi):
        """Finds and highlights input groups connected to the selected output group."""
        output_ports = self._get_ports_in_group(output_group_item)
        if not output_ports: return

        input_tree = self.midi_input_tree if is_midi else self.input_tree
        highlight_func = self._highlight_group_item # Use the new group highlight function

        try:
            connected_input_groups = set() # Store names of groups to highlight

            # Iterate through all ports in the selected output group
            for output_name in output_ports:
                try:
                    # Check if output port exists before querying
                    if not any(p.name == output_name for p in self.client.get_ports(is_output=True, is_midi=is_midi)):
                        continue
                    # Get all connections *from* this specific output port
                    connections = self.client.get_all_connections(output_name)
                    for input_port in connections:
                        # Find the group this connected input port belongs to
                        input_item = input_tree.port_items.get(input_port.name)
                        if input_item and input_item.parent():
                            connected_input_groups.add(input_item.parent().text(0))
                except jack.JackError:
                    continue # Ignore errors for individual ports

            # Highlight the identified groups
            for group_name in connected_input_groups:
                highlight_func(input_tree, group_name)

        except jack.JackError as e:
            print(f"Error highlighting connected input groups: {e}")

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

    def _highlight_group_item(self, tree_widget, group_name):
        """Highlight a specific group item in a tree widget"""
        group_item = tree_widget.port_groups.get(group_name)
        if group_item:
            # Use the auto_highlight_color for connected groups
            group_item.setForeground(0, QBrush(self.auto_highlight_color))

    def clear_highlights(self):
        self._clear_tree_highlights(self.input_tree)
        self._clear_tree_highlights(self.output_tree)

    def clear_midi_highlights(self):
        self._clear_tree_highlights(self.midi_input_tree)
        self._clear_tree_highlights(self.midi_output_tree)

    def _clear_tree_highlights(self, tree_widget):
        """Clear highlights from all group and port items in a tree widget"""
        if not hasattr(tree_widget, 'topLevelItemCount'): return # Safety check

        for i in range(tree_widget.topLevelItemCount()):
            group_item = tree_widget.topLevelItem(i)
            # Reset group item highlight
            group_item.setForeground(0, QBrush(self.text_color))
            # Reset child item highlights
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

    def _are_groups_connected(self, output_ports, input_ports):
        """Check if *any* connection exists between the two groups of ports."""
        try:
            for output_port in output_ports:
                # Check if this output port exists before querying connections
                # Use appropriate is_midi check based on port name heuristic or context if available
                is_midi_heuristic = any('midi' in p.lower() for p in [output_port] + input_ports)
                if not any(p.name == output_port for p in self.client.get_ports(is_output=True, is_midi=is_midi_heuristic)):
                     continue # Skip if output port doesn't exist (e.g., just unregistered)

                connections = self.client.get_all_connections(output_port)
                conn_names = [c.name for c in connections]
                # Check if any connection target is within the input_ports list
                if any(inp in conn_names for inp in input_ports):
                    return True # Found at least one connection between the groups
            return False # No connections found between any ports in the groups
        except jack.JackError as e:
            print(f"Error checking group connection status: {e}")
            return False # Assume not connected on error

    # Helper function (can be placed inside or outside the class)
    def _get_ports_from_selected_items(self, tree_widget):
        """
        Returns a list of unique port names from selected items (ports and groups) in a tree.
        If a group is selected, all its child ports are included.
        """
        port_names = set() # Use a set to automatically handle duplicates
        for item in tree_widget.selectedItems():
            if not item: continue

            # Check if item is visible (basic check, might need refinement if filtering is complex)
            # if item.isHidden(): continue # This check might be needed depending on filter implementation

            if item.childCount() == 0: # Is a port item (leaf)
                port_name = item.data(0, Qt.ItemDataRole.UserRole)
                if port_name:
                    port_names.add(port_name)
            else: # Is a group item
                for i in range(item.childCount()):
                    child = item.child(i)
                    # Check if child is visible
                    # if child.isHidden(): continue
                    port_name = child.data(0, Qt.ItemDataRole.UserRole)
                    if port_name:
                        port_names.add(port_name)
        return list(port_names) # Return as a list
        return port_names

    def _check_if_any_connection_exists(self, output_ports, input_ports):
        """Checks if at least one connection exists between any output port and any input port."""
        if not output_ports or not input_ports:
            return False
        try:
            for out_port in output_ports:
                # Check connections for this output port
                # Need to handle potential JackError if port disappears during check
                try:
                    connections = self.client.get_all_connections(out_port)
                    connected_inputs = {c.name for c in connections}
                    # If any of the desired input ports are connected to this output port, return True
                    if any(in_port in connected_inputs for in_port in input_ports):
                        return True
                except jack.JackError:
                    continue # Ignore error for this specific output port (might have disconnected)
            # If we checked all output ports and found no connections to the desired inputs
            return False
        except jack.JackError as e:
            # Broader error during the process
            print(f"Error checking connections: {e}")
            return False # Assume no connection on error

    def _update_port_connection_buttons(self, input_tree, output_tree, connect_button, disconnect_button):
        """Update connection button states based on selected ports (handles multi-select)."""
        # Get lists of selected port names (only leaf items)
        selected_input_ports = self._get_ports_from_selected_items(input_tree)
        selected_output_ports = self._get_ports_from_selected_items(output_tree)

        # Enable connect button only if at least one port is selected in BOTH trees
        can_connect = bool(selected_input_ports and selected_output_ports)
        connect_button.setEnabled(can_connect)

        # Enable disconnect button only if a connection exists between ANY selected output and ANY selected input
        can_disconnect = False
        if can_connect: # Only check for connections if we have selections in both trees
            can_disconnect = self._are_groups_connected(selected_output_ports, selected_input_ports)

        disconnect_button.setEnabled(can_disconnect)


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

        # Stop latency test process before closing
        if hasattr(self, 'latency_process') and self.latency_process is not None:
            self.stop_latency_test()

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
