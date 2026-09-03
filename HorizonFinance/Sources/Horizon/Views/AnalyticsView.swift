import SwiftUI
import Charts

struct AnalyticsView: View {
    @EnvironmentObject private var store: Store

    @State private var rangeMonths: Int = 12
    @State private var selectedMonth: MonthKey = MonthKey.current

    private var analytics: Analytics { store.analytics }
    private var currency: String { store.currency }
    private var stats: [MonthStats] { analytics.lastStats(rangeMonths) }

    var body: some View {
        PageScroll {
            rangeBar
            flowChartCard
            capitalChartCard
            savingsRateCard
            breakdownCard
            tableCard
        }
    }

    // MARK: Переключатель диапазона

    private var rangeBar: some View {
        HStack {
            SectionTitle(title: "Помесячная картина", subtitle: "факты, темп и прогноз в одном месте")
            Spacer()
            Picker("Период", selection: $rangeMonths) {
                Text("6 мес.").tag(6)
                Text("12 мес.").tag(12)
                Text("24 мес.").tag(24)
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .frame(width: 260)
        }
    }

    // MARK: Доходы и расходы

    private struct FlowPoint: Identifiable {
        var id: String { "\(month.id)-\(series)" }
        var month: MonthKey
        var series: String
        var value: Double
    }

    private var flowPoints: [FlowPoint] {
        var points: [FlowPoint] = []
        for item in stats {
            points.append(FlowPoint(month: item.month, series: "Доход", value: item.income))
            points.append(FlowPoint(month: item.month, series: "Обязательные", value: item.essential))
            points.append(FlowPoint(month: item.month, series: "Свободные", value: item.flexible))
        }
        return points
    }

    private var monthLabels: [String] { stats.map { $0.month.shortTitle } }

    private var flowChartCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            SectionTitle(
                title: "Доходы и расходы по месяцам",
                subtitle: "линия — то, что осталось (доход минус расходы)"
            )
            Chart {
                ForEach(flowPoints) { point in
                    BarMark(
                        x: .value("Месяц", point.month.shortTitle),
                        y: .value("Сумма", point.value)
                    )
                    .foregroundStyle(by: .value("Тип", point.series))
                    .position(by: .value("Тип", point.series))
                    .cornerRadius(3)
                }
                ForEach(stats) { month in
                    LineMark(
                        x: .value("Месяц", month.month.shortTitle),
                        y: .value("Осталось", month.net),
                        series: .value("Тип", "Осталось")
                    )
                    .foregroundStyle(Palette.accent)
                    .lineStyle(StrokeStyle(lineWidth: 2))
                    .symbol(.circle)
                }
            }
            .chartForegroundStyleScale([
                "Доход": Palette.green,
                "Обязательные": Palette.teal,
                "Свободные": Palette.violet
            ])
            .chartXScale(domain: monthLabels)
            .chartLegend(position: .top, alignment: .leading)
            .frame(height: 260)
        }
        .cardStyle()
    }

    // MARK: Капитал и прогноз

    private var capitalChartCard: some View {
        let history = analytics.capitalHistory(months: rangeMonths)
        let forecast = analytics.capitalForecast(months: 12)
        let nearestGoal = store.forecasts.first(where: { !$0.isDone })
        let pace = analytics.pace

        return VStack(alignment: .leading, spacing: 12) {
            SectionTitle(
                title: "Накопленный капитал",
                subtitle: "сплошная линия — факт, пунктир — прогноз при темпе \(Fmt.money(pace.value, code: currency))/мес."
            )
            Chart {
                ForEach(history) { point in
                    AreaMark(
                        x: .value("Месяц", point.month.startDate),
                        y: .value("Капитал", point.value)
                    )
                    .foregroundStyle(
                        LinearGradient(
                            colors: [Palette.accent.opacity(0.28), Palette.accent.opacity(0.02)],
                            startPoint: .top,
                            endPoint: .bottom
                        )
                    )
                }
                ForEach(history) { point in
                    LineMark(
                        x: .value("Месяц", point.month.startDate),
                        y: .value("Капитал", point.value),
                        series: .value("Ряд", "Факт")
                    )
                    .foregroundStyle(Palette.accent)
                    .lineStyle(StrokeStyle(lineWidth: 2.5))
                }
                ForEach(forecast) { point in
                    LineMark(
                        x: .value("Месяц", point.month.startDate),
                        y: .value("Капитал", point.value),
                        series: .value("Ряд", "Прогноз")
                    )
                    .foregroundStyle(Palette.teal)
                    .lineStyle(StrokeStyle(lineWidth: 2, dash: [5, 4]))
                }
                if let goal = nearestGoal {
                    RuleMark(y: .value("Цель", goal.goal.targetAmount))
                        .foregroundStyle(Color(hex: goal.goal.colorHex).opacity(0.7))
                        .lineStyle(StrokeStyle(lineWidth: 1, dash: [3, 3]))
                        .annotation(position: .top, alignment: .leading) {
                            Text("\(goal.goal.emoji) \(goal.goal.title) — \(Fmt.money(goal.goal.targetAmount, code: currency))")
                                .font(.caption2)
                                .foregroundStyle(Palette.muted)
                        }
                }
            }
            .chartXAxis {
                AxisMarks(values: .automatic(desiredCount: 6)) { _ in
                    AxisGridLine()
                    AxisValueLabel(format: .dateTime.month(.abbreviated).year(.twoDigits))
                }
            }
            .frame(height: 260)

            Text("Прогноз пересчитывается сам: чем выше реальный темп последних месяцев, тем круче пунктир и ближе даты целей.")
                .font(.caption)
                .foregroundStyle(Palette.muted)
        }
        .cardStyle()
    }

    // MARK: Норма сбережений

    private var savingsRateCard: some View {
        let plan = store.data.profile.savingsPlan
        return VStack(alignment: .leading, spacing: 12) {
            SectionTitle(
                title: "Сколько остаётся от дохода",
                subtitle: "норма сбережений по месяцам, % от дохода"
            )
            Chart {
                ForEach(stats) { month in
                    BarMark(
                        x: .value("Месяц", month.month.shortTitle),
                        y: .value("Норма", month.savingsRate * 100)
                    )
                    .foregroundStyle(month.net >= 0 ? Palette.green.opacity(0.85) : Palette.red.opacity(0.85))
                    .cornerRadius(3)
                }
            }
            .chartXScale(domain: monthLabels)
            .frame(height: 180)

            HStack(spacing: 18) {
                KeyValueRow(key: "План откладывать", value: "\(Fmt.money(plan, code: currency))/мес.")
                KeyValueRow(
                    key: "Средний темп факта",
                    value: "\(Fmt.money(analytics.pace.value, code: currency))/мес.",
                    valueColor: analytics.pace.value >= plan ? Palette.green : Palette.amber,
                    bold: true
                )
            }
        }
        .cardStyle()
    }

    // MARK: Разбивка по категориям

    private var breakdownCard: some View {
        let slices = Array(analytics.expenseBreakdown(month: selectedMonth).prefix(10))
        return VStack(alignment: .leading, spacing: 12) {
            HStack {
                SectionTitle(title: "Куда ушли деньги", subtitle: "расходы выбранного месяца по категориям")
                Spacer()
                Picker("Месяц", selection: $selectedMonth) {
                    ForEach(analytics.lastStats(rangeMonths).reversed()) { month in
                        Text(month.month.listTitle).tag(month.month)
                    }
                }
                .labelsHidden()
                .frame(width: 190)
            }

            if slices.isEmpty {
                Text("В этом месяце расходов не было.")
                    .font(.subheadline)
                    .foregroundStyle(Palette.muted)
                    .padding(.vertical, 20)
            } else {
                Chart {
                    ForEach(slices) { slice in
                        BarMark(
                            x: .value("Сумма", slice.amount),
                            y: .value("Категория", "\(slice.emoji) \(slice.name)")
                        )
                        .foregroundStyle(Palette.categoryColor(slice.kind))
                        .cornerRadius(4)
                        .annotation(position: .trailing) {
                            Text(Fmt.money(slice.amount, code: currency))
                                .font(.caption2)
                                .foregroundStyle(Palette.muted)
                        }
                    }
                }
                .frame(height: max(CGFloat(slices.count) * 30 + 30, 120))

                HStack(spacing: 16) {
                    legendDot(color: Palette.teal, text: "Обязательные")
                    legendDot(color: Palette.violet, text: "Свободные — то, что и создаёт красную зону")
                }
                .font(.caption)
                .foregroundStyle(Palette.muted)
            }
        }
        .cardStyle()
    }

    private func legendDot(color: Color, text: String) -> some View {
        HStack(spacing: 6) {
            Circle().fill(color).frame(width: 8, height: 8)
            Text(text)
        }
    }

    // MARK: Таблица по месяцам

    private var tableCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionTitle(title: "Таблица по месяцам", subtitle: "те же числа, если хочется просто посмотреть глазами")

            Grid(alignment: .leading, horizontalSpacing: 14, verticalSpacing: 8) {
                GridRow {
                    Text("Месяц").gridColumnAlignment(.leading)
                    Text("Доход").gridColumnAlignment(.trailing)
                    Text("Обязательные").gridColumnAlignment(.trailing)
                    Text("Свободные").gridColumnAlignment(.trailing)
                    Text("Осталось").gridColumnAlignment(.trailing)
                    Text("Норма").gridColumnAlignment(.trailing)
                }
                .font(.caption.weight(.semibold))
                .foregroundStyle(Palette.muted)

                Divider().gridCellUnsizedAxes(.horizontal)

                ForEach(stats.reversed()) { month in
                    GridRow {
                        Text(month.month.listTitle.capitalizedFirst)
                            .font(.subheadline)
                        Text(Fmt.money(month.income, code: currency))
                            .font(.subheadline.monospacedDigit())
                        Text(Fmt.money(month.essential, code: currency))
                            .font(.subheadline.monospacedDigit())
                        Text(Fmt.money(month.flexible, code: currency))
                            .font(.subheadline.monospacedDigit())
                            .foregroundStyle(overLimit(month) ? Palette.red : Palette.ink)
                        Text(Fmt.signedMoney(month.net, code: currency))
                            .font(.subheadline.monospacedDigit().weight(.medium))
                            .foregroundStyle(month.net >= 0 ? Palette.green : Palette.red)
                        Text(month.income > 0 ? Fmt.percent(month.savingsRate) : "—")
                            .font(.subheadline.monospacedDigit())
                            .foregroundStyle(Palette.muted)
                    }
                }
            }

            Text("Красным выделены месяцы, где свободные траты вышли за лимит \(Fmt.money(store.data.profile.flexibleLimit, code: currency)).")
                .font(.caption)
                .foregroundStyle(Palette.muted)
        }
        .cardStyle()
    }

    private func overLimit(_ month: MonthStats) -> Bool {
        let limit = store.data.profile.flexibleLimit
        return limit > 0 && month.flexible > limit
    }
}
