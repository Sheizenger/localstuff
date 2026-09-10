import SwiftUI
import HorizonCore

public enum Palette {
    public static let accent = Color(hex: "#4F8DF7")
    public static let violet = Color(hex: "#8E7CF0")
    public static let green = Color(hex: "#2FBF71")
    public static let amber = Color(hex: "#F5A524")
    public static let red = Color(hex: "#E5484D")
    public static let teal = Color(hex: "#12B0A0")
    public static let ink = Color.primary
    public static let muted = Color.secondary

    /// Палитра для целей — на выбор в редакторе.
    public static let goalColors: [String] = [
        "#4F8DF7", "#2FBF71", "#F5A524", "#E5484D",
        "#8E7CF0", "#12B0A0", "#E8618C", "#7A8899"
    ]

    public static func categoryColor(_ kind: SpendKind) -> Color {
        kind == .essential ? teal : violet
    }
}

extension Zone {
    public var color: Color {
        switch self {
        case .safe: return Palette.green
        case .warning: return Palette.amber
        case .danger: return Palette.red
        }
    }

    public var icon: String {
        switch self {
        case .safe: return "checkmark.circle.fill"
        case .warning: return "exclamationmark.triangle.fill"
        case .danger: return "flame.fill"
        }
    }
}

extension Color {
    public init(hex: String) {
        var cleaned = hex.trimmingCharacters(in: .whitespacesAndNewlines)
        if cleaned.hasPrefix("#") { cleaned.removeFirst() }
        var value: UInt64 = 0
        Scanner(string: cleaned).scanHexInt64(&value)

        let r, g, b: Double
        if cleaned.count == 6 {
            r = Double((value >> 16) & 0xFF) / 255
            g = Double((value >> 8) & 0xFF) / 255
            b = Double(value & 0xFF) / 255
        } else {
            r = 0.4
            g = 0.5
            b = 0.9
        }
        self.init(red: r, green: g, blue: b)
    }
}

public enum Metrics {
    public static let corner: CGFloat = 16
    public static let cardPadding: CGFloat = 18
    public static let gap: CGFloat = 16
}

extension View {
    /// Единая «карточка» — на ней держится вся вёрстка приложения.
    public func cardStyle(tint: Color? = nil) -> some View {
        self
            .padding(Metrics.cardPadding)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                RoundedRectangle(cornerRadius: Metrics.corner, style: .continuous)
                    .fill(.regularMaterial)
            )
            .overlay(
                RoundedRectangle(cornerRadius: Metrics.corner, style: .continuous)
                    .strokeBorder((tint ?? Color.primary).opacity(tint == nil ? 0.08 : 0.35), lineWidth: 1)
            )
    }
}
