import SwiftUI
import HorizonCore

// MARK: - Заголовок секции

public struct SectionTitle: View {
    public var title: String
    public var subtitle: String? = nil
    public var systemImage: String? = nil

    public init(title: String, subtitle: String? = nil, systemImage: String? = nil) {
        self.title = title
        self.subtitle = subtitle
        self.systemImage = systemImage
    }

    public var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            if let systemImage = systemImage {
                Image(systemName: systemImage)
                    .foregroundStyle(Palette.muted)
            }
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.headline)
                if let subtitle = subtitle {
                    Text(subtitle)
                        .font(.caption)
                        .foregroundStyle(Palette.muted)
                }
            }
            Spacer(minLength: 0)
        }
    }
}

// MARK: - Плитка с числом

public struct StatTile: View {
    public var icon: String
    public var title: String
    public var value: String
    public var caption: String? = nil
    public var tint: Color = Palette.accent

    public init(icon: String, title: String, value: String, caption: String? = nil, tint: Color = Palette.accent) {
        self.icon = icon
        self.title = title
        self.value = value
        self.caption = caption
        self.tint = tint
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                Image(systemName: icon)
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(tint)
                    .frame(width: 22, height: 22)
                    .background(Circle().fill(tint.opacity(0.15)))
                Text(title)
                    .font(.caption)
                    .foregroundStyle(Palette.muted)
                Spacer(minLength: 0)
            }
            Text(value)
                .font(.system(size: 22, weight: .semibold, design: .rounded))
                .lineLimit(1)
                .minimumScaleFactor(0.6)
            if let caption = caption {
                Text(caption)
                    .font(.caption2)
                    .foregroundStyle(Palette.muted)
                    .lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, minHeight: 104, alignment: .topLeading)
        .background(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .fill(.regularMaterial)
        )
        .overlay(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .strokeBorder(Color.primary.opacity(0.07), lineWidth: 1)
        )
    }
}

// MARK: - Кольцо прогресса

public struct ProgressRing: View {
    public var progress: Double
    public var color: Color
    public var lineWidth: CGFloat = 10
    public var size: CGFloat = 92
    public var centerTop: String
    public var centerBottom: String? = nil

    public init(
        progress: Double,
        color: Color,
        lineWidth: CGFloat = 10,
        size: CGFloat = 92,
        centerTop: String,
        centerBottom: String? = nil
    ) {
        self.progress = progress
        self.color = color
        self.lineWidth = lineWidth
        self.size = size
        self.centerTop = centerTop
        self.centerBottom = centerBottom
    }

    public var body: some View {
        ZStack {
            Circle()
                .stroke(color.opacity(0.16), lineWidth: lineWidth)
            Circle()
                .trim(from: 0, to: CGFloat(progress.clamped(0, 1)))
                .stroke(
                    color,
                    style: StrokeStyle(lineWidth: lineWidth, lineCap: .round)
                )
                .rotationEffect(.degrees(-90))
                .animation(.easeInOut(duration: 0.35), value: progress)
            VStack(spacing: 1) {
                Text(centerTop)
                    .font(.system(size: size * 0.22, weight: .semibold, design: .rounded))
                if let centerBottom = centerBottom {
                    Text(centerBottom)
                        .font(.system(size: size * 0.12))
                        .foregroundStyle(Palette.muted)
                }
            }
        }
        .frame(width: size, height: size)
    }
}

// MARK: - Полоса лимита с отметкой прогноза

public struct MeterBar: View {
    public var value: Double
    public var limit: Double
    public var zone: Zone
    /// Прогноз на конец месяца — рисуется отдельной риской.
    public var projection: Double? = nil
    public var height: CGFloat = 14

    public init(value: Double, limit: Double, zone: Zone, projection: Double? = nil, height: CGFloat = 14) {
        self.value = value
        self.limit = limit
        self.zone = zone
        self.projection = projection
        self.height = height
    }

    private var fill: Double {
        guard limit > 0 else { return value > 0 ? 1 : 0 }
        return (value / limit).clamped(0, 1)
    }

    private var projectionFill: Double? {
        guard let projection = projection, limit > 0 else { return nil }
        return (projection / limit).clamped(0, 1)
    }

    public var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                Capsule()
                    .fill(Color.primary.opacity(0.08))
                Capsule()
                    .fill(
                        LinearGradient(
                            colors: [zone.color.opacity(0.75), zone.color],
                            startPoint: .leading,
                            endPoint: .trailing
                        )
                    )
                    .frame(width: max(geo.size.width * CGFloat(fill), fill > 0 ? 6 : 0))
                    .animation(.easeInOut(duration: 0.3), value: fill)

                if let projectionFill = projectionFill, projectionFill > fill + 0.01 {
                    RoundedRectangle(cornerRadius: 1)
                        .fill(Color.primary.opacity(0.45))
                        .frame(width: 2, height: height + 6)
                        .offset(x: max(geo.size.width * CGFloat(projectionFill) - 1, 0))
                }
            }
        }
        .frame(height: height)
    }
}

// MARK: - Бейдж зоны

public struct ZoneBadge: View {
    public var zone: Zone
    public var text: String? = nil

    public init(zone: Zone, text: String? = nil) {
        self.zone = zone
        self.text = text
    }

    public var body: some View {
        HStack(spacing: 5) {
            Image(systemName: zone.icon)
                .font(.system(size: 10, weight: .bold))
            Text(text ?? zone.title)
                .font(.caption.weight(.semibold))
        }
        .padding(.horizontal, 9)
        .padding(.vertical, 5)
        .background(Capsule().fill(zone.color.opacity(0.16)))
        .foregroundStyle(zone.color)
    }
}

// MARK: - Мини-столбики

public struct MiniBars: View {
    public var values: [Double]
    public var labels: [String]
    public var positiveColor: Color = Palette.green
    public var negativeColor: Color = Palette.red

    public init(values: [Double], labels: [String], positiveColor: Color = Palette.green, negativeColor: Color = Palette.red) {
        self.values = values
        self.labels = labels
        self.positiveColor = positiveColor
        self.negativeColor = negativeColor
    }

    private var maxAbs: Double {
        max(values.map { abs($0) }.max() ?? 1, 1)
    }

    public var body: some View {
        HStack(alignment: .bottom, spacing: 6) {
            ForEach(Array(values.enumerated()), id: \.offset) { index, value in
                VStack(spacing: 5) {
                    Spacer(minLength: 0)
                    RoundedRectangle(cornerRadius: 4, style: .continuous)
                        .fill(value >= 0 ? positiveColor.opacity(0.85) : negativeColor.opacity(0.85))
                        .frame(height: max(CGFloat(abs(value) / maxAbs) * 74, 3))
                    Text(index < labels.count ? labels[index] : "")
                        .font(.system(size: 9))
                        .foregroundStyle(Palette.muted)
                        .lineLimit(1)
                }
                .frame(maxWidth: .infinity)
            }
        }
        .frame(height: 100)
    }
}

// MARK: - Пустое состояние

public struct EmptyState: View {
    public var icon: String
    public var title: String
    public var message: String
    public var actionTitle: String? = nil
    public var action: (() -> Void)? = nil

    public init(
        icon: String,
        title: String,
        message: String,
        actionTitle: String? = nil,
        action: (() -> Void)? = nil
    ) {
        self.icon = icon
        self.title = title
        self.message = message
        self.actionTitle = actionTitle
        self.action = action
    }

    public var body: some View {
        VStack(spacing: 12) {
            Image(systemName: icon)
                .font(.system(size: 34, weight: .light))
                .foregroundStyle(Palette.muted)
            Text(title)
                .font(.headline)
            Text(message)
                .font(.subheadline)
                .foregroundStyle(Palette.muted)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 380)
            if let actionTitle = actionTitle, let action = action {
                Button(actionTitle, action: action)
                    .buttonStyle(.borderedProminent)
                    .padding(.top, 4)
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 40)
    }
}

// MARK: - Строка «ключ — значение»

public struct KeyValueRow: View {
    public var key: String
    public var value: String
    public var valueColor: Color = Palette.ink
    public var bold: Bool = false

    public init(key: String, value: String, valueColor: Color = Palette.ink, bold: Bool = false) {
        self.key = key
        self.value = value
        self.valueColor = valueColor
        self.bold = bold
    }

    public var body: some View {
        HStack(alignment: .firstTextBaseline) {
            Text(key)
                .font(.subheadline)
                .foregroundStyle(Palette.muted)
            Spacer(minLength: 12)
            Text(value)
                .font(bold ? .subheadline.weight(.semibold) : .subheadline)
                .foregroundStyle(valueColor)
        }
    }
}

// MARK: - Поле для суммы

public struct AmountField: View {
    public var title: String
    @Binding public var value: Double
    public var currency: String

    public init(title: String, value: Binding<Double>, currency: String) {
        self.title = title
        self._value = value
        self.currency = currency
    }

    public var body: some View {
        HStack {
            TextField(title, value: $value, format: .number.precision(.fractionLength(0...2)))
                .textFieldStyle(.roundedBorder)
                .multilineTextAlignment(.trailing)
            Text(Fmt.symbol(for: currency))
                .foregroundStyle(Palette.muted)
                .frame(width: 24, alignment: .leading)
        }
    }
}
