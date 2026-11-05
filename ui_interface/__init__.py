"""UI Interface - Futuristic JARVIS-style HUD using PyQt5"""
import sys
import math
import random
from typing import Optional, Callable, List
from dataclasses import dataclass
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFrame, QTextEdit, QGraphicsView, 
    QGraphicsScene, QGraphicsItem
)
from PyQt5.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve, QPoint, 
    QRectF, pyqtSignal, QThread, QSize
)
from PyQt5.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QLinearGradient,
    QRadialGradient, QFontDatabase, QPixmap, QCursor
)

from config.settings import ui_config, voice_config, system_config
from utils.logger import get_logger

logger = get_logger("ui_interface")

# JARVIS color scheme
COLORS = {
    "primary": QColor(0, 212, 255),      # Cyan
    "secondary": QColor(255, 107, 0),     # Orange
    "accent": QColor(0, 255, 136),       # Green
    "warning": QColor(255, 204, 0),      # Yellow
    "danger": QColor(255, 50, 50),       # Red
    "bg": QColor(10, 10, 15),            # Dark background
    "bg_light": QColor(20, 20, 30),      # Lighter background
    "text": QColor(230, 230, 230),       # Light text
    "text_dim": QColor(150, 150, 150),   # Dim text
}

class VoiceWaveformWidget(QWidget):
    """Animated voice waveform visualizer"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(300, 100)
        self.amplitude = 0.3
        self.frequency = 0.02
        self.phase = 0
        self.bar_count = 30
        self.bars = [0.3] * self.bar_count
        self.is_active = False
        
        # Animation timer
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._animate)
        self.timer.start(30)
    
    def set_active(self, active: bool):
        """Set waveform active state"""
        self.is_active = active
    
    def set_amplitude(self, amplitude: float):
        """Set waveform amplitude (0-1)"""
        self.amplitude = max(0, min(1, amplitude))
    
    def _animate(self):
        """Animate waveform"""
        self.phase += 0.1
        
        if self.is_active:
            # Generate dynamic bars
            for i in range(self.bar_count):
                # Combine sine waves for organic motion
                val = (
                    math.sin(self.phase + i * self.frequency) * 0.5 + 0.5 +
                    math.sin(self.phase * 1.5 + i * 0.05) * 0.3 +
                    random.uniform(-0.1, 0.1)
                )
                self.bars[i] = max(0.1, min(1.0, val * self.amplitude))
        else:
            # Idle state - low amplitude gentle wave
            for i in range(self.bar_count):
                val = math.sin(self.phase * 0.5 + i * 0.1) * 0.1 + 0.15
                self.bars[i] = val
        
        self.update()
    
    def paintEvent(self, event):
        """Paint waveform"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        width = self.width()
        height = self.height()
        bar_width = width / self.bar_count
        
        for i, bar_height in enumerate(self.bars):
            x = i * bar_width + bar_width * 0.1
            bar_w = bar_width * 0.8
            bar_h = bar_height * height * 0.8
            y = (height - bar_h) / 2
            
            # Gradient based on height
            if self.is_active:
                color = COLORS["primary"]
                alpha = int(150 + bar_height * 105)
            else:
                color = COLORS["text_dim"]
                alpha = 100
            
            bar_color = QColor(color)
            bar_color.setAlpha(alpha)
            
            painter.fillRect(
                int(x), int(y), int(bar_w), int(bar_h),
                bar_color
            )
        
        painter.end()

class CircularHUDWidget(QWidget):
    """Circular JARVIS-style HUD display"""
    
    def __init__(self, parent=None, size: int = 400):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.size = size
        
        # Animation state
        self.rotation = 0
        self.pulse_phase = 0
        self.inner_radius = 0.6
        self.state = "idle"  # idle, listening, processing, speaking
        
        # Animation timer
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._animate)
        self.timer.start(16)  # ~60 FPS
    
    def set_state(self, state: str):
        """Set HUD state"""
        self.state = state
        self.update()
    
    def _animate(self):
        """Animate HUD elements"""
        self.rotation += 2
        self.pulse_phase += 0.05
        self.update()
    
    def paintEvent(self, event):
        """Paint circular HUD"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        center = self.rect().center()
        radius = min(self.width(), self.height()) / 2 - 20
        
        # Background gradient
        bg_gradient = QRadialGradient(center, radius)
        bg_gradient.setColorAt(0, QColor(5, 5, 10))
        bg_gradient.setColorAt(1, QColor(10, 10, 15))
        painter.fillRect(self.rect(), bg_gradient)
        
        # State-based colors
        if self.state == "listening":
            main_color = COLORS["accent"]
        elif self.state == "processing":
            main_color = COLORS["warning"]
        elif self.state == "speaking":
            main_color = COLORS["primary"]
        else:
            main_color = COLORS["text_dim"]
        
        # Outer ring
        pen = QPen(main_color)
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawEllipse(center, int(radius), int(radius))
        
        # Rotating arc
        painter.save()
        painter.translate(center)
        painter.rotate(self.rotation)
        
        pen = QPen(COLORS["primary"])
        pen.setWidth(3)
        painter.setPen(pen)
        painter.drawArc(
            int(-radius * 0.95), int(-radius * 0.95),
            int(radius * 1.9), int(radius * 1.9),
            0, 120 * 16
        )
        painter.restore()
        
        # Inner rotating ring (opposite direction)
        painter.save()
        painter.translate(center)
        painter.rotate(-self.rotation * 0.7)
        
        pen = QPen(COLORS["secondary"])
        pen.setWidth(2)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        inner_r = radius * 0.75
        painter.drawEllipse(QPoint(0, 0), int(inner_r), int(inner_r))
        painter.restore()
        
        # Pulse effect when active
        if self.state != "idle":
            pulse_size = abs(math.sin(self.pulse_phase)) * 10
            pen = QPen(main_color)
            pen.setWidth(1)
            pen.setStyle(Qt.DotLine)
            painter.setPen(pen)
            painter.drawEllipse(
                center,
                int(radius + pulse_size),
                int(radius + pulse_size)
            )
        
        # Center JARVIS indicator
        center_radius = radius * 0.3
        
        # Center glow
        glow_alpha = int(50 + abs(math.sin(self.pulse_phase * 2)) * 50)
        glow_color = QColor(main_color)
        glow_color.setAlpha(glow_alpha)
        painter.setBrush(glow_color)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(center, int(center_radius), int(center_radius))
        
        # Center circle border
        pen = QPen(main_color)
        pen.setWidth(2)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(center, int(center_radius * 0.7), int(center_radius * 0.7))
        
        # State indicator in center
        painter.setPen(COLORS["text"])
        font = QFont("Segoe UI", 10, QFont.Bold)
        painter.setFont(font)
        
        state_text = self.state.upper()
        text_rect = painter.boundingRect(
            int(center.x() - 50), int(center.y() - 10), 100, 20,
            Qt.AlignCenter, state_text
        )
        painter.drawText(text_rect, Qt.AlignCenter, state_text)
        
        # Decorative ticks
        pen = QPen(COLORS["text_dim"])
        pen.setWidth(1)
        painter.setPen(pen)
        
        for i in range(12):
            angle = i * 30
            painter.save()
            painter.translate(center)
            painter.rotate(angle)
            
            tick_start = radius * 0.85
            tick_end = radius * 0.92
            painter.drawLine(0, int(-tick_start), 0, int(-tick_end))
            painter.restore()
        
        painter.end()

class StatusPanel(QWidget):
    """System status indicators panel"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(200)
        self.indicators = {}
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        
        # Title
        title = QLabel("SYSTEM STATUS")
        title.setStyleSheet("""
            QLabel {
                color: #00D4FF;
                font-size: 12px;
                font-weight: bold;
                border-bottom: 1px solid #00D4FF;
                padding-bottom: 5px;
            }
        """)
        layout.addWidget(title)
        
        # Status indicators
        self._add_indicator("Voice Engine", "Offline", layout)
        self._add_indicator("AI Brain", "Offline", layout)
        self._add_indicator("Memory", "Active", layout)
        self._add_indicator("Browser", "Standby", layout)
        self._add_indicator("Integrations", "3/4 Active", layout)
        
        layout.addStretch()
    
    def _add_indicator(self, name: str, status: str, layout):
        container = QWidget()
        hlayout = QHBoxLayout(container)
        hlayout.setSpacing(10)
        hlayout.setContentsMargins(0, 0, 0, 0)
        
        # Status dot
        dot = QLabel("●")
        dot.setStyleSheet("color: #FF6B00; font-size: 10px;")
        hlayout.addWidget(dot)
        
        # Name
        name_label = QLabel(name)
        name_label.setStyleSheet("color: #969696; font-size: 11px;")
        hlayout.addWidget(name_label)
        
        hlayout.addStretch()
        
        # Status
        status_label = QLabel(status)
        status_label.setStyleSheet("color: #E6E6E6; font-size: 11px;")
        hlayout.addWidget(status_label)
        
        layout.addWidget(container)
        
        self.indicators[name] = {
            "dot": dot,
            "status": status_label
        }
    
    def update_status(self, name: str, status: str, is_active: bool = True):
        """Update status indicator"""
        if name in self.indicators:
            self.indicators[name]["status"].setText(status)
            color = "#00FF88" if is_active else "#FF6B00"
            self.indicators[name]["dot"].setStyleSheet(f"color: {color}; font-size: 10px;")

class ChatDisplay(QTextEdit):
    """Chat display with JARVIS styling"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMinimumHeight(200)
        
        # Style
        self.setStyleSheet("""
            QTextEdit {
                background-color: #0A0A0F;
                color: #E6E6E6;
                border: 1px solid #1A1A2F;
                border-radius: 8px;
                padding: 10px;
                font-family: 'Segoe UI', sans-serif;
                font-size: 13px;
            }
        """)
    
    def add_user_message(self, text: str):
        """Add user message"""
        html = f"""
        <div style="margin: 10px 0;">
            <span style="color: #00FF88; font-weight: bold;">USER:</span>
            <span style="color: #E6E6E6;">{text}</span>
        </div>
        """
        self.append(html)
    
    def add_jarvis_message(self, text: str, emotion: str = "neutral"):
        """Add JARVIS response"""
        colors = {
            "neutral": "#00D4FF",
            "satisfied": "#00FF88",
            "concerned": "#FFCC00",
            "witty": "#FF6B00",
            "inquisitive": "#00D4FF"
        }
        color = colors.get(emotion, "#00D4FF")
        
        html = f"""
        <div style="margin: 10px 0;">
            <span style="color: {color}; font-weight: bold;">JARVIS:</span>
            <span style="color: #E6E6E6;">{text}</span>
        </div>
        """
        self.append(html)
    
    def add_system_message(self, text: str):
        """Add system message"""
        html = f"""
        <div style="margin: 5px 0; color: #646464; font-size: 11px; font-style: italic;">
            {text}
        </div>
        """
        self.append(html)
    
    def clear_chat(self):
        """Clear chat display"""
        self.clear()

class MainWindow(QMainWindow):
    """Main JARVIS application window"""
    
    # Signals for integration with backend
    voice_command = pyqtSignal(str)
    interrupt_requested = pyqtSignal()
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("J.A.R.V.I.S.")
        self.setMinimumSize(1200, 800)
        
        # Set dark theme
        self.setStyleSheet("""
            QMainWindow {
                background-color: #0A0A0F;
            }
            QWidget {
                background-color: #0A0A0F;
                color: #E6E6E6;
                font-family: 'Segoe UI', sans-serif;
            }
            QPushButton {
                background-color: #1A1A2F;
                color: #00D4FF;
                border: 1px solid #00D4FF;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #00D4FF;
                color: #0A0A0F;
            }
            QPushButton:pressed {
                background-color: #0088AA;
            }
        """)
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup main UI layout"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QHBoxLayout(central_widget)
        main_layout.setSpacing(20)
        main_layout.setContentsMargins(20, 20, 20, 20)
        
        # Left panel - Status
        self.status_panel = StatusPanel()
        main_layout.addWidget(self.status_panel)
        
        # Center panel - Main HUD and chat
        center_panel = QWidget()
        center_layout = QVBoxLayout(center_panel)
        center_layout.setSpacing(20)
        
        # HUD
        hud_container = QWidget()
        hud_layout = QVBoxLayout(hud_container)
        hud_layout.setAlignment(Qt.AlignCenter)
        
        self.hud = CircularHUDWidget(size=350)
        hud_layout.addWidget(self.hud, alignment=Qt.AlignCenter)
        
        # Waveform
        self.waveform = VoiceWaveformWidget()
        hud_layout.addWidget(self.waveform)
        
        center_layout.addWidget(hud_container)
        
        # Chat display
        self.chat_display = ChatDisplay()
        center_layout.addWidget(self.chat_display)
        
        # Input area
        input_container = QWidget()
        input_layout = QHBoxLayout(input_container)
        
        self.text_input = QTextEdit()
        self.text_input.setPlaceholderText("Type your command or press the microphone button...")
        self.text_input.setMaximumHeight(60)
        self.text_input.setStyleSheet("""
            QTextEdit {
                background-color: #1A1A2F;
                border: 1px solid #2A2A3F;
                border-radius: 6px;
                padding: 8px;
                color: #E6E6E6;
            }
        """)
        input_layout.addWidget(self.text_input)
        
        # Send button
        send_btn = QPushButton("➤")
        send_btn.setFixedSize(60, 60)
        send_btn.setStyleSheet("""
            QPushButton {
                background-color: #00D4FF;
                color: #0A0A0F;
                border-radius: 30px;
                font-size: 20px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #00FFFF;
            }
        """)
        send_btn.clicked.connect(self._on_send_clicked)
        input_layout.addWidget(send_btn)
        
        # Voice button
        self.voice_btn = QPushButton("🎤")
        self.voice_btn.setFixedSize(60, 60)
        self.voice_btn.setCheckable(True)
        self.voice_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF6B00;
                color: #0A0A0F;
                border-radius: 30px;
                font-size: 20px;
            }
            QPushButton:checked {
                background-color: #00FF88;
            }
            QPushButton:hover {
                background-color: #FF8833;
            }
        """)
        self.voice_btn.clicked.connect(self._on_voice_clicked)
        input_layout.addWidget(self.voice_btn)
        
        center_layout.addWidget(input_container)
        
        main_layout.addWidget(center_panel, stretch=2)
        
        # Right panel - Quick actions
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setSpacing(10)
        
        quick_title = QLabel("QUICK ACTIONS")
        quick_title.setStyleSheet("""
            QLabel {
                color: #00D4FF;
                font-size: 12px;
                font-weight: bold;
                border-bottom: 1px solid #00D4FF;
                padding-bottom: 5px;
            }
        """)
        right_layout.addWidget(quick_title)
        
        quick_actions = [
            ("Weather", lambda: self.voice_command.emit("What's the weather?")),
            ("News", lambda: self.voice_command.emit("What's the news?")),
            ("Open Browser", lambda: self.voice_command.emit("Open Chrome")),
            ("Study Mode", lambda: self.voice_command.emit("Study mode")),
            ("Work Mode", lambda: self.voice_command.emit("Work mode")),
        ]
        
        for name, action in quick_actions:
            btn = QPushButton(name)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #1A1A2F;
                    color: #969696;
                    border: 1px solid #2A2A3F;
                    text-align: left;
                    padding-left: 15px;
                }
                QPushButton:hover {
                    background-color: #2A2A3F;
                    color: #00D4FF;
                    border-color: #00D4FF;
                }
            """)
            btn.clicked.connect(action)
            right_layout.addWidget(btn)
        
        right_layout.addStretch()
        
        # Interrupt button
        interrupt_btn = QPushButton("⏹ STOP")
        interrupt_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF3333;
                color: white;
                border: none;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #FF6666;
            }
        """)
        interrupt_btn.clicked.connect(self.interrupt_requested.emit)
        right_layout.addWidget(interrupt_btn)
        
        main_layout.addWidget(right_panel)
    
    def _on_send_clicked(self):
        """Handle text send"""
        text = self.text_input.toPlainText().strip()
        if text:
            self.chat_display.add_user_message(text)
            self.voice_command.emit(text)
            self.text_input.clear()
    
    def _on_voice_clicked(self):
        """Handle voice button toggle"""
        if self.voice_btn.isChecked():
            self.voice_command.emit("__WAKE__")
        else:
            self.interrupt_requested.emit()
    
    def set_voice_state(self, state: str):
        """Update UI based on voice state"""
        self.hud.set_state(state)
        
        if state == "listening":
            self.waveform.set_active(True)
            self.waveform.set_amplitude(0.8)
            self.voice_btn.setChecked(True)
            self.status_panel.update_status("Voice Engine", "Listening", True)
        elif state == "speaking":
            self.waveform.set_active(True)
            self.waveform.set_amplitude(0.5)
            self.status_panel.update_status("Voice Engine", "Speaking", True)
        elif state == "processing":
            self.waveform.set_active(False)
            self.waveform.set_amplitude(0.4)
            self.status_panel.update_status("AI Brain", "Processing", True)
        else:  # idle
            self.waveform.set_active(False)
            self.waveform.set_amplitude(0.2)
            self.voice_btn.setChecked(False)
            self.status_panel.update_status("Voice Engine", "Standby", False)
    
    def add_message(self, sender: str, text: str, emotion: str = "neutral"):
        """Add message to chat"""
        if sender == "user":
            self.chat_display.add_user_message(text)
        else:
            self.chat_display.add_jarvis_message(text, emotion)
    
    def add_system_message(self, text: str):
        """Add system message"""
        self.chat_display.add_system_message(text)
    
    def update_status(self, component: str, status: str, active: bool = True):
        """Update status panel"""
        self.status_panel.update_status(component, status, active)
    
    def keyPressEvent(self, event):
        """Handle key press"""
        if event.key() == Qt.Key_Return and event.modifiers() == Qt.ControlModifier:
            self._on_send_clicked()
        elif event.key() == Qt.Key_Escape:
            self.interrupt_requested.emit()
        else:
            super().keyPressEvent(event)

class UIInterface:
    """Main UI interface for backend integration"""
    
    def __init__(self):
        self.app = None
        self.window = None
        self._on_command: Optional[Callable] = None
        self._on_interrupt: Optional[Callable] = None
    
    def initialize(self):
        """Initialize UI"""
        self.app = QApplication(sys.argv)
        self.window = MainWindow()
        
        # Connect signals
        self.window.voice_command.connect(self._handle_command)
        self.window.interrupt_requested.connect(self._handle_interrupt)
        
        logger.info("UI initialized")
    
    def _handle_command(self, text: str):
        """Handle command from UI"""
        if self._on_command:
            self._on_command(text)
    
    def _handle_interrupt(self):
        """Handle interrupt from UI"""
        if self._on_interrupt:
            self._on_interrupt()
    
    def set_command_handler(self, handler: Callable[[str], None]):
        """Set command handler"""
        self._on_command = handler
    
    def set_interrupt_handler(self, handler: Callable[[], None]):
        """Set interrupt handler"""
        self._on_interrupt = handler
    
    def show(self):
        """Show the UI"""
        if self.window:
            self.window.show()
    
    def run(self):
        """Run the application"""
        if self.app:
            self.show()
            return self.app.exec_()
        return 0
    
    def set_voice_state(self, state: str):
        """Set voice state in UI"""
        if self.window:
            from PyQt5.QtCore import QTimer
            QTimer.singleShot(0, lambda: self.window.set_voice_state(state))
    
    def add_message(self, sender: str, text: str, emotion: str = "neutral"):
        """Add message to UI - handle system messages too"""
        if sender == "system":
            # System message
            if self.window:
                from PyQt5.QtCore import QTimer
                QTimer.singleShot(0, lambda: self.window.add_system_message(text))
        elif sender == "user":
            if self.window:
                from PyQt5.QtCore import QTimer
                QTimer.singleShot(0, lambda: self.window.add_user_message(text))
        else:
            if self.window:
                from PyQt5.QtCore import QTimer
                QTimer.singleShot(0, lambda: self.window.add_jarvis_message(text, emotion))
    
    def update_status(self, component: str, status: str, active: bool = True):
        """Update status in UI"""
        if self.window:
            from PyQt5.QtCore import QTimer
            QTimer.singleShot(0, lambda: self.window.update_status(component, status, active))
    
    def close(self):
        """Close the UI"""
        if self.window:
            self.window.close()
        if self.app:
            self.app.quit()
