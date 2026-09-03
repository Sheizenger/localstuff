import SwiftUI
import Charts

struct GoalsView: View {
    @EnvironmentObject private var store: Store
    @EnvironmentObject private var bus: UIBus

    @State private var editingGoal: Goal? = nil

    private var currency: String { store.currency }
    private var forecasts: [GoalForecast] { store.forecasts }

    var body: some View {
        PageScroll {
            planCard
            if forecasts.isEmpty {
                EmptyState(
                    icon: "target",
                    title: "Целей пока нет",
                    message: "Цель — это то, ради чего вы держите лимит трат. Подушка, машина, первый взнос: приложение само посчитает срок при вашем темпе.",
                    actionTitle: "Добавить цель",
                    action: { bus.showAddGoal = true }
                )
                .cardStyle()
            } else {
                goalsGrid
                timelineCard
            }
        }
        .sheet(item: $editingGoal) { goal in
            GoalEditor(mode: .edit(goal))
                .environmentObject(store)
        }
    }

    // MARK: Как распределяются деньги

    private var planCard: some View {
        let pace = store.analytics.pace
        let allocated = forecasts.reduce(0.0) { $0 + $1.monthly }
        return VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .top) {
                SectionTitle(
                    title: "Как распределяется темп",
                    subtitle: "\(Fmt.money(pace.value, code: currency)) в месяц · \(pace.isPlanned ? "план из настроек" : pace.basis)"
                )
                Button {
                    bus.showAddGoal = true
                } label: {
                    Label("Новая цель", systemImage: "plus")
                }
                .buttonStyle(.borderedProminent)
            }

            distribution

            HStack(spacing: 20) {
                KeyValueRow(key: "Распределено", value: "\(Fmt.money(allocated, code: currency))/мес.", bold: true)
                KeyValueRow(key: "Свободно от целей", value: "\(Fmt.money(max(pace.value - allocated, 0), code: currency))/мес.")
            }

            if overSubscribed {
                Label("Доли параллельных целей в сумме больше 100% — они пересчитаны пропорционально, чтобы уложиться в темп.",
                      systemImage: "info.circle")
                    .font(.caption)
                    .foregroundStyle(Palette.amber)
                    .fixedSize(horizontal: false, vertical: true)
            }

            if store.analytics.freeCash > 0 && forecasts.contains(where: { !$0.isDone }) {
                Label("Свободными лежит \(Fmt.money(store.analytics.freeCash, code: currency)). Прогресс целей растёт только после кнопки «Пополнить» — так видно, что решение принято, а не просто осталось на карте.",
                      systemImage: "arrow.down.to.line")
                    .font(.caption)
                    .foregroundStyle(Palette.muted)
                    .fixedSize(horizontal: false, vertical: true)
            }

            if pace.value <= 0 {
                Label("Темп нулевой или отрицательный: за последние месяцы расходы съедали весь доход. Пока темп не станет положительным, сроки не считаются.",
                      systemImage: "exclamationmark.triangle.fill")
                    .font(.caption)
                    .foregroundStyle(Palette.amber)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .cardStyle()
    }

    /// Две строки-«дорожки»: кто копится параллельно и кто стоит в очереди.
    private var distribution: some View {
        let open = forecasts.filter { !$0.isDone }
        let parallel = open.filter { $0.funding == .parallel }
        let queued = open.filter { $0.funding == .queued }
        return VStack(alignment: .leading, spacing: 8) {
            distributionRow(
                funding: .parallel,
                items: parallel,
                summary: parallel.isEmpty
                    ? "Пока никто — цели можно перевести сюда в карточке или в редакторе"
                    : parallel.map { "\($0.goal.emoji) \($0.goal.title) · \(Fmt.percent($0.goal.share))" }.joined(separator: "   ")
            )
            distributionRow(
                funding: .queued,
                items: queued,
                summary: queued.isEmpty
                    ? "Очередь пуста — остаток темпа просто остаётся свободным"
                    : queued.enumerated().map { "\($0.offset + 1). \($0.element.goal.emoji) \($0.element.goal.title)" }.joined(separator: "   ")
            )
        }
    }

    private func distributionRow(funding: GoalFunding, items: [GoalForecast], summary: String) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Label(funding.title, systemImage: funding.icon)
                .font(.caption.weight(.semibold))
                .padding(.horizontal, 8)
                .padding(.vertical, 4)
                .background(
                    Capsule().fill((funding == .parallel ? Palette.accent : Palette.teal).opacity(0.15))
                )
                .foregroundStyle(funding == .parallel ? Palette.accent : Palette.teal)
                .frame(width: 140, alignment: .leading)

            Text(summary)
                .font(.caption)
                .foregroundStyle(items.isEmpty ? Palette.muted : Palette.ink)
                .fixedSize(horizontal: false, vertical: true)

            Spacer(minLength: 0)
        }
    }

    /// Доли параллельных целей в сумме превышают темп — движок их нормирует.
    private var overSubscribed: Bool {
        let sum = forecasts
            .filter { !$0.isDone && $0.funding == .parallel }
            .reduce(0.0) { $0 + max($1.goal.share, 0) }
        return sum > 1.0001
    }

    // MARK: Карточки целей

    private var goalsGrid: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 340), spacing: Metrics.gap)], spacing: Metrics.gap) {
            ForEach(forecasts) { forecast in
                GoalCard(
                    forecast: forecast,
                    currency: currency,
                    onEdit: { editingGoal = forecast.goal },
                    onTopUp: { bus.contributionTarget = forecast.goal },
                    onMoveUp: { store.moveGoal(forecast.goal, up: true) },
                    onMoveDown: { store.moveGoal(forecast.goal, up: false) },
                    onToggleFunding: { store.toggleFunding(forecast.goal) }
                )
            }
        }
    }

    // MARK: Лента сроков

    private struct TimelineItem: Identifiable {
        var id: UUID
        var title: String
        var color: Color
        var start: Date
        var end: Date
    }

    private var timelineItems: [TimelineItem] {
        let now = Date()
        return forecasts.compactMap { forecast in
            guard !forecast.isDone, let months = forecast.months, months.isFinite, months < 360 else { return nil }
            let start = Forecaster.dateAfter(months: forecast.startsInMonths, from: now)
            let end = Forecaster.dateAfter(months: months, from: now)
            guard end > start else { return nil }
            return TimelineItem(
                id: forecast.goal.id,
                title: "\(forecast.goal.emoji) \(forecast.goal.title)",
                color: Color(hex: forecast.goal.colorHex),
                start: start,
                end: end
            )
        }
    }

    @ViewBuilder
    private var timelineCard: some View {
        let items = timelineItems
        if !items.isEmpty {
            VStack(alignment: .leading, spacing: 12) {
                SectionTitle(
                    title: "Лента достижения",
                    subtitle: "полоса начинается там, где цель получает первые деньги, и кончается на закрытии"
                )
                Chart {
                    ForEach(items) { item in
                        BarMark(
                            xStart: .value("Старт", item.start),
                            xEnd: .value("Готово", item.end),
                            y: .value("Цель", item.title)
                        )
                        .foregroundStyle(item.color.opacity(0.85))
                        .cornerRadius(6)
                    }
                    RuleMark(x: .value("Сегодня", Date()))
                        .foregroundStyle(Palette.muted.opacity(0.6))
                        .lineStyle(StrokeStyle(lineWidth: 1, dash: [4, 3]))
                }
                .chartXAxis {
                    AxisMarks(values: .automatic(desiredCount: 6)) { value in
                        AxisGridLine()
                        AxisValueLabel(format: .dateTime.month(.abbreviated).year(.twoDigits))
                    }
                }
                .frame(height: max(CGFloat(items.count) * 44 + 40, 120))
            }
            .cardStyle()
        }
    }
}

// MARK: - Карточка цели

struct GoalCard: View {
    var forecast: GoalForecast
    var currency: String
    var onEdit: () -> Void
    var onTopUp: () -> Void
    var onMoveUp: () -> Void
    var onMoveDown: () -> Void
    var onToggleFunding: () -> Void

    private var color: Color { Color(hex: forecast.goal.colorHex) }

    private var fundingColor: Color {
        forecast.funding == .parallel ? Palette.accent : Palette.teal
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            header
            progressBlock
            Divider().opacity(0.5)
            details
            footerButtons
        }
        .cardStyle(tint: forecast.isDone ? Palette.green : nil)
    }

    private var header: some View {
        HStack(alignment: .top, spacing: 10) {
            Text(forecast.goal.emoji)
                .font(.title2)
                .frame(width: 38, height: 38)
                .background(Circle().fill(color.opacity(0.15)))

            VStack(alignment: .leading, spacing: 4) {
                Text(forecast.goal.title)
                    .font(.headline)
                fundingBadge
                if !forecast.goal.note.isEmpty {
                    Text(forecast.goal.note)
                        .font(.caption)
                        .foregroundStyle(Palette.muted)
                        .lineLimit(2)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }

            Spacer(minLength: 0)

            Menu {
                Button("Пополнить", action: onTopUp)
                Button("Изменить", action: onEdit)
                Divider()
                Button(forecast.funding == .parallel ? "Поставить в очередь" : "Копить параллельно",
                       action: onToggleFunding)
                Divider()
                Button("Выше по приоритету", action: onMoveUp)
                Button("Ниже по приоритету", action: onMoveDown)
            } label: {
                Image(systemName: "ellipsis.circle")
            }
            .menuStyle(.borderlessButton)
            .frame(width: 28)
        }
    }

    /// Как эта цель финансируется — видно прямо на карточке, без захода в редактор.
    private var fundingBadge: some View {
        HStack(spacing: 5) {
            Image(systemName: forecast.funding.icon)
                .font(.system(size: 9, weight: .bold))
            Text(forecast.funding == .parallel
                 ? "параллельно · доля \(Fmt.percent(forecast.goal.share))"
                 : "в очереди")
                .font(.caption2.weight(.medium))
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 3)
        .background(Capsule().fill(fundingColor.opacity(0.14)))
        .foregroundStyle(fundingColor)
    }

    private var progressBlock: some View {
        HStack(spacing: 16) {
            ProgressRing(
                progress: forecast.progress,
                color: forecast.isDone ? Palette.green : color,
                lineWidth: 9,
                size: 82,
                centerTop: Fmt.percent(forecast.progress),
                centerBottom: forecast.isDone ? "готово" : nil
            )
            VStack(alignment: .leading, spacing: 5) {
                Text(Fmt.money(forecast.saved, code: currency))
                    .font(.system(size: 22, weight: .semibold, design: .rounded))
                Text("из \(Fmt.money(forecast.goal.targetAmount, code: currency))")
                    .font(.caption)
                    .foregroundStyle(Palette.muted)
                if !forecast.isDone {
                    Text("осталось \(Fmt.money(forecast.remaining, code: currency))")
                        .font(.caption)
                        .foregroundStyle(Palette.muted)
                }
            }
            Spacer(minLength: 0)
        }
    }

    private var details: some View {
        VStack(alignment: .leading, spacing: 7) {
            if forecast.isDone {
                Label("Цель закрыта", systemImage: "checkmark.seal.fill")
                    .font(.subheadline.weight(.medium))
                    .foregroundStyle(Palette.green)
            } else {
                KeyValueRow(key: "Срок при текущем темпе", value: forecast.horizonText, bold: true)
                KeyValueRow(key: "Ожидаемая дата", value: forecast.etaText)
                if forecast.isQueued {
                    KeyValueRow(
                        key: "Старт финансирования",
                        value: "через \(Fmt.horizon(months: forecast.startsInMonths))",
                        valueColor: Palette.amber
                    )
                    KeyValueRow(key: "Сейчас получает", value: "ничего — ждёт очереди")
                } else {
                    KeyValueRow(key: "Взнос в месяц", value: Fmt.money(forecast.monthly, code: currency))
                }
                if let deadline = forecast.goal.deadline {
                    KeyValueRow(key: "Желаемый срок", value: Fmt.dayShort.string(from: deadline))
                }
                if let required = forecast.requiredMonthly, forecast.goal.deadline != nil {
                    KeyValueRow(
                        key: "Нужно в месяц к сроку",
                        value: Fmt.money(required, code: currency),
                        valueColor: required > forecast.monthly ? Palette.amber : Palette.green
                    )
                }
            }

            if let zone = forecast.deadlineZone, !forecast.isDone {
                ZoneBadge(zone: zone, text: deadlineText(zone))
                    .padding(.top, 2)
            }
        }
    }

    private var footerButtons: some View {
        HStack {
            Button("Пополнить", action: onTopUp)
                .buttonStyle(.borderedProminent)
            Button("Изменить", action: onEdit)
            Spacer()
        }
    }

    private func deadlineText(_ zone: Zone) -> String {
        guard let slack = forecast.deadlineSlack else { return "" }
        if slack <= -900 { return "срок недостижим при текущем распределении" }
        switch zone {
        case .safe: return "успеваем, запас \(Fmt.horizon(months: slack))"
        case .warning: return "впритык к сроку"
        case .danger: return "опаздываем на \(Fmt.horizon(months: abs(slack)))"
        }
    }
}
