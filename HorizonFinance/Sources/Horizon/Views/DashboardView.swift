import SwiftUI

struct DashboardView: View {
    @EnvironmentObject private var store: Store
    @EnvironmentObject private var bus: UIBus

    private var analytics: Analytics { store.analytics }
    private var currency: String { store.currency }

    var body: some View {
        PageScroll {
            if store.data.transactions.isEmpty {
                onboardingCard
            }
            heroCard
            tiles
            HStack(alignment: .top, spacing: Metrics.gap) {
                zoneCard
                paceCard
            }
            horizonCard
            monthsCard
        }
    }

    // MARK: Первый запуск

    private var onboardingCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Начните с трёх шагов")
                .font(.headline)
            Text("1. В «Настройках» укажите лимит свободных трат и валюту.\n2. Добавьте цели — хотя бы подушку.\n3. Заносите операции: доходы и расходы. Прогноз пересчитается сам.")
                .font(.subheadline)
                .foregroundStyle(Palette.muted)
                .fixedSize(horizontal: false, vertical: true)
            HStack {
                Button("Добавить операцию") { bus.showAddTransaction = true }
                    .buttonStyle(.borderedProminent)
                Button("Загрузить демо-данные") { store.loadDemoData() }
                Button("Открыть настройки") { bus.section = .settings }
            }
            .padding(.top, 4)
        }
        .cardStyle(tint: Palette.accent)
    }

    // MARK: Верхняя карточка

    private var heroCard: some View {
        let status = analytics.budgetStatus
        return HStack(alignment: .top, spacing: 24) {
            VStack(alignment: .leading, spacing: 6) {
                Text(analytics.currentMonth.fullTitle)
                    .font(.caption)
                    .foregroundStyle(Palette.muted)
                Text(Fmt.money(analytics.freeCash, code: currency))
                    .font(.system(size: 40, weight: .semibold, design: .rounded))
                    .lineLimit(1)
                    .minimumScaleFactor(0.5)
                Text("свободные деньги — вне целей")
                    .font(.caption)
                    .foregroundStyle(Palette.muted)

                HStack(spacing: 10) {
                    ZoneBadge(zone: status.zone, text: status.headline)
                }
                .padding(.top, 6)
            }

            Spacer(minLength: 0)

            VStack(alignment: .trailing, spacing: 10) {
                miniStat("Всего капитала", Fmt.money(analytics.totalCapital, code: currency))
                miniStat("В целях", Fmt.money(analytics.totalInGoals, code: currency))
                miniStat("Хватит на", Fmt.horizon(months: analytics.runwayMonths))
            }
        }
        .cardStyle()
    }

    private func miniStat(_ title: String, _ value: String) -> some View {
        VStack(alignment: .trailing, spacing: 1) {
            Text(title)
                .font(.caption2)
                .foregroundStyle(Palette.muted)
            Text(value)
                .font(.system(size: 15, weight: .medium, design: .rounded))
        }
    }

    // MARK: Плитки

    private var tiles: some View {
        let month = analytics.thisMonth
        let pace = analytics.pace
        return LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 12), count: 4), spacing: 12) {
            StatTile(
                icon: "arrow.down.circle.fill",
                title: "Доход в этом месяце",
                value: Fmt.money(month.income, code: currency),
                caption: month.income > 0 ? "норма сбережений \(Fmt.percent(month.savingsRate))" : "пока пусто",
                tint: Palette.green
            )
            StatTile(
                icon: "arrow.up.circle.fill",
                title: "Расходы",
                value: Fmt.money(month.expense, code: currency),
                caption: "обязательные \(Fmt.money(month.essential, code: currency)) · свободные \(Fmt.money(month.flexible, code: currency))",
                tint: Palette.red
            )
            StatTile(
                icon: "arrow.down.to.line",
                title: "Переведено в цели",
                value: Fmt.money(month.moved, code: currency),
                caption: "план: \(Fmt.money(store.data.profile.savingsPlan, code: currency))/мес.",
                tint: Palette.accent
            )
            StatTile(
                icon: "speedometer",
                title: "Темп накоплений",
                value: Fmt.money(pace.value, code: currency),
                caption: pace.isPlanned ? "по плану из настроек" : pace.basis,
                tint: pace.value > 0 ? Palette.teal : Palette.amber
            )
        }
    }

    // MARK: Красная зона

    private var zoneCard: some View {
        let status = analytics.budgetStatus
        return VStack(alignment: .leading, spacing: 12) {
            HStack {
                SectionTitle(title: "Запас свободных трат", subtitle: "лимит на «всякое» в этом месяце")
                ZoneBadge(zone: status.zone)
            }

            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Text(Fmt.money(status.spent, code: currency))
                    .font(.system(size: 26, weight: .semibold, design: .rounded))
                Text("из \(Fmt.money(status.limit, code: currency))")
                    .font(.subheadline)
                    .foregroundStyle(Palette.muted)
            }

            MeterBar(value: status.spent, limit: status.limit, zone: status.zone, projection: status.projected)

            HStack {
                Text(status.remaining >= 0
                     ? "Осталось \(Fmt.money(status.remaining, code: currency))"
                     : "Перерасход \(Fmt.money(-status.remaining, code: currency))")
                    .font(.caption)
                    .foregroundStyle(status.remaining >= 0 ? Palette.muted : Palette.red)
                Spacer()
                Text("до конца месяца \(Fmt.daysWord(status.daysLeft))")
                    .font(.caption)
                    .foregroundStyle(Palette.muted)
            }

            Text(status.advice)
                .font(.callout)
                .foregroundStyle(Palette.ink)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.top, 2)

            if status.projected > status.limit && status.limit > 0 {
                Label("Прогноз на конец месяца при таком темпе — \(Fmt.money(status.projected, code: currency))",
                      systemImage: "chart.line.uptrend.xyaxis")
                    .font(.caption)
                    .foregroundStyle(Palette.amber)
            }
        }
        .cardStyle(tint: status.zone == .safe ? nil : status.zone.color)
    }

    // MARK: Темп

    private var paceCard: some View {
        let pace = analytics.pace
        let plan = store.data.profile.savingsPlan
        let delta = pace.value - plan
        return VStack(alignment: .leading, spacing: 12) {
            SectionTitle(title: "Темп накоплений", subtitle: pace.isPlanned ? "пока по плану — данных мало" : "по факту, \(pace.basis)")

            HStack(alignment: .center, spacing: 16) {
                ProgressRing(
                    progress: plan > 0 ? pace.value / plan : 0,
                    color: delta >= 0 ? Palette.green : Palette.amber,
                    lineWidth: 11,
                    size: 96,
                    centerTop: plan > 0 ? Fmt.percent((pace.value / plan).clamped(0, 2)) : "—",
                    centerBottom: "от плана"
                )
                VStack(alignment: .leading, spacing: 6) {
                    KeyValueRow(key: "Факт", value: "\(Fmt.money(pace.value, code: currency))/мес.", bold: true)
                    KeyValueRow(key: "План", value: "\(Fmt.money(plan, code: currency))/мес.")
                    KeyValueRow(
                        key: delta >= 0 ? "Опережение" : "Отставание",
                        value: Fmt.money(abs(delta), code: currency),
                        valueColor: delta >= 0 ? Palette.green : Palette.amber
                    )
                    if pace.monthsUsed > 0 {
                        Text("Считается по \(Fmt.monthsWord(pace.monthsUsed)) с данными")
                            .font(.caption2)
                            .foregroundStyle(Palette.muted)
                    }
                }
            }
        }
        .cardStyle()
    }

    // MARK: Горизонт целей

    private var horizonCard: some View {
        let items = store.forecasts.filter { !$0.isDone }.prefix(3)
        return VStack(alignment: .leading, spacing: 14) {
            HStack {
                SectionTitle(title: "Ближайший горизонт", subtitle: "срок при текущем темпе")
                Button("Все цели") { bus.section = .goals }
                    .buttonStyle(.link)
            }

            if items.isEmpty {
                EmptyState(
                    icon: "target",
                    title: "Целей пока нет",
                    message: "Добавьте хотя бы одну — приложение сразу посчитает срок при вашем темпе.",
                    actionTitle: "Добавить цель",
                    action: { bus.showAddGoal = true }
                )
            } else {
                ForEach(Array(items)) { forecast in
                    GoalHorizonRow(forecast: forecast, currency: currency)
                    if forecast.id != items.last?.id {
                        Divider()
                    }
                }
            }
        }
        .cardStyle()
    }

    // MARK: Последние месяцы

    private var monthsCard: some View {
        let stats = analytics.lastStats(6)
        return VStack(alignment: .leading, spacing: 12) {
            HStack {
                SectionTitle(title: "Что оставалось по месяцам", subtitle: "доход минус расходы")
                Button("Аналитика") { bus.section = .analytics }
                    .buttonStyle(.link)
            }
            MiniBars(
                values: stats.map { $0.net },
                labels: stats.map { $0.month.shortTitle }
            )
        }
        .cardStyle()
    }
}

/// Строка цели на «Обзоре»: прогресс, срок и месячный взнос.
struct GoalHorizonRow: View {
    var forecast: GoalForecast
    var currency: String

    var body: some View {
        HStack(spacing: 14) {
            ProgressRing(
                progress: forecast.progress,
                color: Color(hex: forecast.goal.colorHex),
                lineWidth: 7,
                size: 56,
                centerTop: Fmt.percent(forecast.progress)
            )

            VStack(alignment: .leading, spacing: 3) {
                Text("\(forecast.goal.emoji) \(forecast.goal.title)")
                    .font(.headline)
                Text("\(Fmt.money(forecast.saved, code: currency)) из \(Fmt.money(forecast.goal.targetAmount, code: currency))")
                    .font(.caption)
                    .foregroundStyle(Palette.muted)
                if forecast.isQueued {
                    Text("В очереди — старт через \(Fmt.horizon(months: forecast.startsInMonths))")
                        .font(.caption2)
                        .foregroundStyle(Palette.amber)
                } else if forecast.monthly > 0 {
                    Text("\(Fmt.money(forecast.monthly, code: currency)) в месяц")
                        .font(.caption2)
                        .foregroundStyle(Palette.muted)
                }
            }

            Spacer(minLength: 8)

            VStack(alignment: .trailing, spacing: 3) {
                Text(forecast.horizonText)
                    .font(.system(size: 15, weight: .semibold, design: .rounded))
                Text(forecast.etaText)
                    .font(.caption)
                    .foregroundStyle(Palette.muted)
                if let zone = forecast.deadlineZone {
                    ZoneBadge(zone: zone, text: deadlineText(zone))
                }
            }
        }
        .padding(.vertical, 2)
    }

    private func deadlineText(_ zone: Zone) -> String {
        guard let slack = forecast.deadlineSlack else { return "" }
        if slack <= -900 { return "срок недостижим" }
        switch zone {
        case .safe: return "успеваем, запас \(Fmt.horizon(months: slack))"
        case .warning: return "впритык к сроку"
        case .danger: return "опоздание \(Fmt.horizon(months: abs(slack)))"
        }
    }
}
