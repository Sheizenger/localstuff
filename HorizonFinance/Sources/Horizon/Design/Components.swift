import SwiftUI

// MARK: - Заголовок секции

struct SectionTitle: View {
    var title: String
    var subtitle: String? = nil
    var systemImage: String? = nil

    var body: some View {
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

struct StatTile: View {
    var icon: String
    var title: String
    var value: String
    var caption: String? = nil
    var tint: Color = Palette.accent

    var body: some View {
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

struct ProgressRing: View {
    var progress: Double
    var color: Color
    var lineWidth: CGFloat = 10
    var size: CGFloat = 92
    var centerTop: String
    var centerBottom: String? = nil

    var body: some View {
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

struct MeterBar: View {
    var value: Double
    var limit: Double
    var zone: Zone
    /// Прогноз на конец месяца — рисуется отдельной риской.
    var projection: Double? = nil
    var height: CGFloat = 14

    private var fill: Double {
        guard limit > 0 else { return value > 0 ? 1 : 0 }
        return (value / limit).clamped(0, 1)
    }

    private var projectionFill: Double? {
        guard let projection = projection, limit > 0 else { return nil }
        return (projection / limit).clamped(0, 1)
    }

    var body: some View {
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

struct ZoneBadge: View {
    var zone: Zone
    var text: String? = nil

    var body: some View {
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

struct MiniBars: View {
    var values: [Double]
    var labels: [String]
    var positiveColor: Color = Palette.green
    var negativeColor: Color = Palette.red

    private var maxAbs: Double {
        max(values.map { abs($0) }.max() ?? 1, 1)
    }

    var body: some View {
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

struct EmptyState: View {
    var icon: String
    var title: String
    var message: String
    var actionTitle: String? = nil
    var action: (() -> Void)? = nil

    var body: some View {
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

struct KeyValueRow: View {
    var key: String
    var value: String
    var valueColor: Color = Palette.ink
    var bold: Bool = false

    var body: some View {
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

struct AmountField: View {
    var title: String
    @Binding var value: Double
    var currency: String

    var body: some View {
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
