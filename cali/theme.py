"""Viewer palettes, stylesheet and theme icon construction."""
from pathlib import Path

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QPalette, QColor, QPixmap, QPainter, QPen, QPainterPath, QIcon


def accent_palette(day_mode):
    if day_mode:
        return {
            "camera": "#5C53A5", "mini": "#A059A0", "gap": "#B84C63",
            "primary": "#5C53A5", "primary_hover": "#4E458F", "primary_text": "#FFFFFF",
            "secondary": "#A059A0", "secondary_hover": "#894A89", "secondary_text": "#FFFFFF",
            "tint": "#EAE5F3", "tint_text": "#51488E", "tint_border": "#C8BDDD",
            "mini_tint": "#F1E4EE", "mini_text": "#864481",
            "gap_tint": "#F8E3E7", "gap_text": "#A23F55",
            "soft": "#F1ECF6", "muted": "#71677F",
        }
    return {
        "camera": "#F3E79B", "mini": "#FAC484", "gap": "#EB7F86",
        "primary": "#393448", "primary_hover": "#494158", "primary_text": "#F3E79B",
        "secondary": "#443443", "secondary_hover": "#564050", "secondary_text": "#FAC484",
        "tint": "#393448", "tint_text": "#F3E79B", "tint_border": "#73647E",
        "mini_tint": "#443443", "mini_text": "#FAC484",
        "gap_tint": "#452F3D", "gap_text": "#F8A07E",
        "soft": "#302D40", "muted": "#D5C3D6",
    }


def theme_icon(day_mode):
    pixmap = QPixmap(48, 48)
    pixmap.setDevicePixelRatio(2)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor("#454D46" if day_mode else "#F3E79B"), 1.7)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    if day_mode:
        moon = QPainterPath()
        moon.moveTo(20, 14)
        moon.cubicTo(15, 16, 8, 10, 11, 3)
        moon.cubicTo(6, 3.5, 3, 7.5, 3, 12)
        moon.cubicTo(3, 17, 7, 21, 12, 21)
        moon.cubicTo(15.5, 21, 19, 18.5, 20, 14)
        painter.drawPath(moon)
    else:
        painter.drawEllipse(QRectF(7.5, 7.5, 9, 9))
        for x1, y1, x2, y2 in (
            (12, 2, 12, 4), (12, 20, 12, 22),
            (2, 12, 4, 12), (20, 12, 22, 12),
            (5, 5, 6.5, 6.5), (17.5, 17.5, 19, 19),
            (5, 19, 6.5, 17.5), (17.5, 6.5, 19, 5),
        ):
            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
    painter.end()
    return QIcon(pixmap)


def app_stylesheet(day_mode):
    stylesheet = """
    QWidget#root {
        background: #F3F7F9;
        color: #13263A;
        font-size: 13px;
    }
    QWidget { selection-background-color: #CDECF5; }

    QFrame#sidebar {
        background: #102131;
        border: 1px solid #173247;
        border-radius: 24px;
    }
    QFrame#sideCard {
        background: #14283A;
        border: 1px solid #213B4F;
        border-radius: 17px;
    }
    QFrame#viewerCard, QFrame#timelineCard {
        background: #FFFFFF;
        border: 1px solid #DCE7EC;
        border-radius: 20px;
    }

    QLabel#brandLogo { background: transparent; }
    QLabel#appTitle {
        color: #F4FAFD;
        font-size: 27px;
        font-weight: 700;
        background: transparent;
    }
    QLabel#sectionTitle {
        color: #F2F8FB;
        font-size: 13px;
        font-weight: 700;
        background: transparent;
    }
    QLabel#mainSectionTitle {
        color: #183249;
        font-size: 13px;
        font-weight: 700;
        background: transparent;
    }
    QLabel#controlLabel {
        color: #B7C7D4;
        font-size: 11px;
        font-weight: 650;
        background: transparent;
    }
    QLabel#navRowLabel {
        color: #D8E5EC;
        font-size: 11px;
        font-weight: 650;
        background: transparent;
    }
    QLabel#navSubhead {
        color: #7FDCE9;
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 0.5px;
        background: transparent;
    }
    QFrame#sideSeparator {
        background: #27485D;
        border: none;
    }
    QLabel#subtleText, QLabel#sidebarBody {
        color: #91A6B7;
        background: transparent;
    }
    QLabel#selectionInfo {
        color: #B5C5D2;
        font-size: 11px;
        background: transparent;
    }

    QLabel#panelTitle {
        color: #173148;
        font-size: 13px;
        font-weight: 700;
        background: transparent;
    }
    QLabel#accentDot {
        font-size: 11px;
        background: transparent;
    }
    QLabel#imageCanvas {
        background: #0B1825;
        color: #728596;
        border: 1px solid #11293B;
        border-radius: 14px;
    }

    QFrame#trimSeparator {
        background: #E5EDF1;
        border: none;
    }
    QLabel#trimTitle {
        color: #173148;
        font-size: 12px;
        font-weight: 700;
        background: transparent;
    }
    QLabel#trimStatusPill {
        background: #EAF5F8;
        color: #4F6A79;
        border: 1px solid #D5E7EC;
        border-radius: 10px;
        padding: 4px 8px;
        font-size: 10px;
        font-weight: 600;
    }

    QPushButton {
        min-height: 32px;
        border-radius: 10px;
        border: 1px solid #CBD8DE;
        background: #FFFFFF;
        color: #183249;
        padding: 6px 10px;
        font-weight: 600;
    }
    QPushButton:hover { background: #F4F8FA; }
    QPushButton:pressed { background: #EAF1F4; }

    QPushButton[variant="source"] {
        min-height: 39px;
        background: #183146;
        color: #EAF5FA;
        border: 1px solid #27475D;
        text-align: left;
        padding: 8px 10px;
        font-size: 11px;
    }
    QPushButton[variant="source"]:hover {
        background: #1C3A51;
        border-color: #315873;
    }

    QPushButton[variant="soft"] {
        background: #193347;
        color: #D9E6ED;
        border: 1px solid #2B4A60;
        min-height: 36px;
    }
    QPushButton[variant="soft"]:hover {
        background: #1E3D54;
        border-color: #37617D;
    }

    QPushButton[variant="navStep"] {
        background: #193347;
        color: #EAF5FA;
        border: 1px solid #2B4A60;
        border-radius: 9px;
        padding: 0;
        font-size: 22px;
        font-weight: 500;
    }
    QPushButton[variant="navStep"]:hover {
        background: #20445D;
        border-color: #3C6C8A;
    }

    QPushButton[variant="teal"] {
        background: #12BEB8;
        color: #062A2A;
        border: 1px solid #12BEB8;
        min-height: 28px;
        padding: 4px 11px;
    }
    QPushButton[variant="teal"]:hover { background: #19CAC4; }

    QPushButton[variant="blue"] {
        background: #1479E8;
        color: #FFFFFF;
        border: 1px solid #1479E8;
        min-height: 28px;
        padding: 4px 12px;
    }
    QPushButton[variant="blue"]:hover { background: #0E6ED7; }

    QPushButton[variant="mainGhost"] {
        background: #F7FAFB;
        color: #365064;
        border: 1px solid #D8E3E8;
        min-height: 28px;
        padding: 4px 10px;
    }
    QPushButton[variant="mainGhost"]:hover { background: #EDF4F7; }

    QPushButton[variant="viewerTool"] {
        min-height: 26px;
        background: #F5FAFC;
        color: #3E596B;
        border: 1px solid #D6E5EB;
        border-radius: 9px;
        padding: 3px 9px;
        font-size: 10px;
    }
    QPushButton[variant="viewerTool"]:hover { background: #EAF6F9; }
    QPushButton[variant="viewerTool"]:checked {
        background: #DDF7FA;
        color: #087F9E;
        border-color: #93DCE7;
    }
    QPushButton[variant="viewerToolAccent"] {
        min-height: 26px;
        background: #1479E8;
        color: #FFFFFF;
        border: 1px solid #1479E8;
        border-radius: 9px;
        padding: 3px 10px;
        font-size: 10px;
    }
    QPushButton[variant="viewerToolAccent"]:hover { background: #0E6ED7; }
    QPushButton:disabled {
        color: #9BAAB4;
        background: #F1F5F7;
        border-color: #E1E9ED;
    }

    QComboBox, QSpinBox {
        min-height: 33px;
        border-radius: 10px;
        background: #183146;
        color: #EEF7FB;
        border: 1px solid #2C4C62;
        padding: 3px 9px;
    }
    QComboBox:hover, QSpinBox:hover { border-color: #3C6B88; }
    QComboBox:focus, QSpinBox:focus { border-color: #17B9DC; }
    QComboBox QAbstractItemView {
        background: #14283A;
        color: #EEF7FB;
        border: 1px solid #2C4C62;
        selection-background-color: #1479E8;
    }

    QLabel { background: transparent; }
    QToolTip {
        background: #0E1D2A;
        color: #F0F8FB;
        border: 1px solid #29475D;
        border-radius: 7px;
        padding: 6px;
    }
    QSplitter::handle {
        background: transparent;
        width: 9px;
    }
    """
    if day_mode:
        stylesheet += """
        QMainWindow, QDialog, QWidget#root {
            background: #F2EEE5;
            color: #353B38;
        }
        QFrame#sidebar {
            background: #E8E2D6;
            border-color: #D6CEBF;
        }
        QFrame#sideCard {
            background: #F3EFE6;
            border-color: #DCD5C8;
        }
        QFrame#viewerCard, QFrame#timelineCard {
            background: #FAF7F0;
            border-color: #DED8CC;
        }
        QLabel#appTitle, QLabel#sectionTitle, QLabel#mainSectionTitle,
        QLabel#panelTitle, QLabel#trimTitle {
            color: #353B38;
        }
        QLabel#controlLabel, QLabel#navRowLabel, QLabel#selectionInfo {
            color: #575C54;
        }
        QLabel#subtleText, QLabel#sidebarBody { color: #686B61; }
        QLabel#navSubhead { color: #287B77; }
        QFrame#sideSeparator, QFrame#trimSeparator { background: #DCD5C8; }
        QLabel#imageCanvas {
            background: #EDE8DE;
            color: #737469;
            border-color: #DCD5C8;
        }
        QLabel#trimStatusPill {
            background: #E8EDE5;
            color: #53675D;
            border-color: #D2DCCE;
        }
        QPushButton, QPushButton[variant="source"],
        QPushButton[variant="soft"], QPushButton[variant="navStep"],
        QPushButton[variant="mainGhost"], QPushButton[variant="viewerTool"] {
            background: #F8F5EE;
            color: #454D46;
            border-color: #D2CCBF;
        }
        QPushButton:hover, QPushButton[variant="source"]:hover,
        QPushButton[variant="soft"]:hover, QPushButton[variant="navStep"]:hover,
        QPushButton[variant="mainGhost"]:hover, QPushButton[variant="viewerTool"]:hover {
            background: #E9E5DA;
            border-color: #B9B6A8;
        }
        QPushButton:pressed { background: #DFDCCF; }
        QPushButton[variant="soft"]:checked,
        QPushButton[variant="viewerTool"]:checked {
            background: #DDEAE1;
            color: #25675C;
            border-color: #ABC9B9;
        }
        QPushButton[variant="teal"] {
            background: #287D71;
            color: #FAF7F0;
            border-color: #287D71;
        }
        QPushButton[variant="teal"]:hover { background: #216B61; }
        QPushButton:disabled {
            background: #EEEAE1;
            color: #96968B;
            border-color: #DFDACE;
        }
        QComboBox, QSpinBox, QComboBox QAbstractItemView {
            background: #F8F5EE;
            color: #454D46;
            border-color: #D2CCBF;
            selection-background-color: #DDEAE1;
            selection-color: #25675C;
        }
        QComboBox:hover, QSpinBox:hover { border-color: #AAAFA0; }
        QComboBox:focus, QSpinBox:focus { border-color: #287D71; }
        QToolTip {
            background: #F8F5EE;
            color: #454D46;
            border-color: #C6C0B3;
        }
        """
    stylesheet += """
        QPushButton#themeToggle {
            min-height: 34px;
            padding: 0;
            border-radius: 18px;
        }
    """
    icon_dir = (Path(__file__).parent / "assets" / "icons").as_posix()
    control_border = "#D2CCBF" if day_mode else "#2C4C62"
    stylesheet += f"""
        QTabWidget::pane {{ border: none; }}
        QTabBar::tab {{
            background: {"#E8E2D6" if day_mode else "#E5EDF1"};
            color: #53675D;
            border-radius: 8px;
            margin-right: 5px;
            padding: 6px 12px;
            font-weight: 600;
        }}
        QTabBar::tab:selected {{
            background: {"#DDEAE1" if day_mode else "#DDF7FA"};
            color: #25675C;
        }}
        QCheckBox, QLabel#calciumStatus {{ color: #686B61; }}
        QCheckBox {{ spacing: 6px; }}
        QCheckBox::indicator {{ width: 14px; height: 14px; }}
        QCheckBox::indicator:checked {{
            background: #287D71; border: 1px solid #287D71; border-radius: 4px;
        }}
        QCheckBox::indicator:unchecked {{
            background: {"#F8F5EE" if day_mode else "#FFFFFF"};
            border: 1px solid #96968B; border-radius: 4px;
        }}
        QTabWidget QComboBox, QTabWidget QSpinBox {{
            background: {"#F8F5EE" if day_mode else "#F1F5F7"};
            color: #454D46;
            border-color: {control_border};
            min-height: 30px;
            max-height: 30px;
            padding: 0 28px 0 8px;
            font-size: 11px;
        }}
        QComboBox#videoMapping, QSpinBox#mp4Offset {{
            min-height: 32px;
            max-height: 32px;
            padding: 0 28px 0 10px;
        }}
        QComboBox#videoMapping::drop-down, QTabWidget QComboBox::drop-down {{
            subcontrol-origin: padding;
            subcontrol-position: top right;
            width: 26px;
            border: none;
            border-left: 1px solid {control_border};
        }}
        QComboBox#videoMapping::down-arrow, QTabWidget QComboBox::down-arrow {{
            image: url("{icon_dir}/chevron-down.svg");
            width: 10px;
            height: 6px;
        }}
        QSpinBox#mp4Offset::up-button, QSpinBox#mp4Offset::down-button,
        QTabWidget QSpinBox::up-button, QTabWidget QSpinBox::down-button {{
            subcontrol-origin: padding;
            width: 22px;
            height: 16px;
            border: none;
            border-left: 1px solid {control_border};
        }}
        QSpinBox#mp4Offset::up-button, QTabWidget QSpinBox::up-button {{ subcontrol-position: top right; }}
        QSpinBox#mp4Offset::down-button, QTabWidget QSpinBox::down-button {{ subcontrol-position: bottom right; }}
        QSpinBox#mp4Offset::up-arrow, QTabWidget QSpinBox::up-arrow {{
            image: url("{icon_dir}/chevron-up.svg");
            width: 8px;
            height: 5px;
        }}
        QSpinBox#mp4Offset::down-arrow, QTabWidget QSpinBox::down-arrow {{
            image: url("{icon_dir}/chevron-down.svg");
            width: 8px;
            height: 5px;
        }}
    """
    if not day_mode:
        stylesheet += """
            QMainWindow, QDialog, QWidget#root { background: #0C1927; color: #EAF5FA; }
            QFrame#viewerCard, QFrame#timelineCard { background: #14283A; border-color: #315067; }
            QLabel#mainSectionTitle, QLabel#panelTitle, QLabel#trimTitle { color: #EAF5FA; }
            QLabel#calciumStatus, QCheckBox { color: #B7C7D4; }
            QFrame#trimSeparator { background: #315067; }
            QPushButton, QPushButton[variant="mainGhost"], QPushButton[variant="viewerTool"] {
                background: #193347; color: #EAF5FA; border-color: #315067;
            }
            QTabWidget QComboBox, QTabWidget QSpinBox {
                background: #193347; color: #EAF5FA; border-color: #315067;
            }
            QCheckBox::indicator:unchecked { background: #14283A; border-color: #728596; }
            QSlider::groove:horizontal { background: #213B4F; }
        """
    accents = accent_palette(day_mode)
    stylesheet += f"""
        QWidget {{ selection-background-color: {accents['tint']}; selection-color: {accents['tint_text']}; }}
        QLabel#navSubhead {{ color: {accents['mini_text']}; }}
        QLabel#trimStatusPill {{
            background: {accents['tint']}; color: {accents['tint_text']}; border-color: {accents['tint_border']};
        }}
        QPushButton[variant="blue"], QPushButton[variant="viewerToolAccent"] {{
            background: {accents['primary']}; color: {accents['primary_text']}; border-color: {accents['primary']};
        }}
        QPushButton[variant="blue"]:hover, QPushButton[variant="viewerToolAccent"]:hover {{
            background: {accents['primary_hover']}; border-color: {accents['primary_hover']};
        }}
        QPushButton[variant="teal"] {{
            background: {accents['secondary']}; color: {accents['secondary_text']}; border-color: {accents['secondary']};
        }}
        QPushButton[variant="teal"]:hover {{
            background: {accents['secondary_hover']}; border-color: {accents['secondary_hover']};
        }}
        QPushButton:hover, QPushButton[variant="source"]:hover,
        QPushButton[variant="soft"]:hover, QPushButton[variant="navStep"]:hover,
        QPushButton[variant="mainGhost"]:hover, QPushButton[variant="viewerTool"]:hover {{
            background: {accents['soft']}; color: {accents['tint_text']}; border-color: {accents['tint_border']};
        }}
        QPushButton[variant="soft"]:checked, QPushButton[variant="viewerTool"]:checked {{
            background: {accents['tint']}; color: {accents['tint_text']}; border-color: {accents['tint_border']};
        }}
        QPushButton:pressed {{ background: {accents['tint']}; color: {accents['tint_text']}; }}
        QPushButton:disabled, QPushButton[variant="blue"]:disabled,
        QPushButton[variant="teal"]:disabled, QPushButton[variant="viewerToolAccent"]:disabled {{
            background: {"#EEEAE1" if day_mode else "#14283A"};
            color: {"#96968B" if day_mode else "#728596"};
            border-color: {"#DFDACE" if day_mode else "#27485D"};
        }}
        QComboBox:focus, QSpinBox:focus, QTabWidget QComboBox:focus, QTabWidget QSpinBox:focus {{
            border-color: {accents['secondary']};
        }}
        QComboBox QAbstractItemView {{
            selection-background-color: {accents['tint']}; selection-color: {accents['tint_text']};
        }}
        QTabBar::tab {{ background: {accents['soft']}; color: {accents['muted']}; }}
        QTabBar::tab:selected {{ background: {accents['tint']}; color: {accents['tint_text']}; }}
        QCheckBox::indicator:checked {{ background: {accents['secondary']}; border-color: {accents['secondary']}; }}
        QSlider::sub-page:horizontal {{ background: {accents['primary']}; }}
        QSlider::handle:horizontal {{ background: {accents['primary']}; border-color: {accents['primary_hover']}; }}
    """
    for role, background, text in (
        ("camera", accents["tint"], accents["tint_text"]),
        ("mini", accents["mini_tint"], accents["mini_text"]),
        ("gap", accents["gap_tint"], accents["gap_text"]),
    ):
        stylesheet += f"""
            QPushButton[accentRole="{role}"] {{
                background: {background}; color: {text}; border-color: {background};
            }}
            QPushButton[accentRole="{role}"]:hover,
            QPushButton[accentRole="{role}"]:pressed {{
                background: {background}; color: {text}; border-color: {text};
            }}
            QPushButton[accentRole="{role}"]:disabled {{
                background: {background}; color: {"#96968B" if day_mode else "#728596"};
                border-color: {background};
            }}
        """
    return stylesheet


def application_palette(default_palette, day_mode):
    palette = QPalette(default_palette)
    if not day_mode:
        for role, color in (
            (QPalette.Window, "#102131"), (QPalette.WindowText, "#EAF5FA"),
            (QPalette.Base, "#14283A"), (QPalette.AlternateBase, "#193347"),
            (QPalette.Text, "#EAF5FA"), (QPalette.Button, "#193347"),
            (QPalette.ButtonText, "#EAF5FA"), (QPalette.ToolTipBase, "#14283A"),
            (QPalette.ToolTipText, "#EAF5FA"), (QPalette.Highlight, "#393448"),
            (QPalette.HighlightedText, "#F3E79B"), (QPalette.PlaceholderText, "#91A6B7"),
            (QPalette.Light, "#315067"), (QPalette.Midlight, "#27485D"),
            (QPalette.Mid, "#213B4F"), (QPalette.Dark, "#0C1927"),
            (QPalette.Shadow, "#08111B"), (QPalette.Link, "#FAC484"),
            (QPalette.LinkVisited, "#CE6693"), (QPalette.Accent, "#A059A0"),
        ):
            palette.setColor(role, QColor(color))
        for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
            palette.setColor(QPalette.Disabled, role, QColor("#728596"))
    return palette
