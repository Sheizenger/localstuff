import SwiftUI
import Charts

struct BasketView: View {
    @EnvironmentObject private var store: Store

    @State private var editingProductID: String? = nil

    private var settings: BasketSettings { store.data.basket }
    private var plan: BasketPlan { BasketPlanner.plan(settings: settings) }

    var body: some View {
        PageScroll {
            setupCard
            summaryTiles
            chainsCard
            splitCard
            factCard
            productsCard
            sourceNote
        }
        .sheet(item: editingProductBinding) { item in
            BasketPriceEditor(productID: item.id)
                .environmentObject(store)
        }
    }

    // MARK: Настройка корзины

    private var setupCard: some View {
        let country = plan.country
        return VStack(alignment: .leading, spacing: 14) {
            SectionTitle(
                title: "Кто и где покупает",
                subtitle: "корзина пересчитывается сразу: страна, город, состав семьи и выбранные сети"
            )

            HStack(spacing: 18) {
                Picker("Страна", selection: countryBinding) {
                    ForEach(BasketCatalog.countries) { item in
                        Text(item.name).tag(item.id)
                    }
                }
                .frame(width: 230)

                Picker("Город", selection: $store.data.basket.cityID) {
                    ForEach(country.cities) { city in
                        Text(city.name).tag(city.id)
                    }
                }
                .frame(width: 250)

                Spacer()
            }

            Divider()

            HStack(alignment: .top, spacing: 26) {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Взрослые")
                        .font(.caption)
                        .foregroundStyle(Palette.muted)
                    Picker("Взрослые", selection: $store.data.basket.adults) {
                        Text("1").tag(1)
                        Text("2").tag(2)
                        Text("3").tag(3)
                    }
                    .pickerStyle(.segmented)
                    .labelsHidden()
                    .frame(width: 160)
                }

                VStack(alignment: .leading, spacing: 6) {
                    Text("Дети")
                        .font(.caption)
                        .foregroundStyle(Palette.muted)
                    Stepper(value: $store.data.basket.infants, in: 0...4) {
                        Text("\(ChildAge.infant.title): \(settings.infants)")
                    }
                    Stepper(value: $store.data.basket.preschoolers, in: 0...4) {
                        Text("\(ChildAge.preschool.title): \(settings.preschoolers)")
                    }
                    Stepper(value: $store.data.basket.schoolers, in: 0...4) {
                        Text("\(ChildAge.school.title): \(settings.schoolers)")
                    }
                }
                .frame(width: 240)

                VStack(alignment: .leading, spacing: 6) {
                    Text("Сети (пусто — считаем все)")
                        .font(.caption)
                        .foregroundStyle(Palette.muted)
                    chainChips
                }

                Spacer(minLength: 0)
            }
        }
        .cardStyle()
    }

    private var chainChips: some View {
        let available = BasketCatalog.availableChains(countryID: settings.countryID, cityID: settings.cityID)
        return LazyVGrid(columns: [GridItem(.adaptive(minimum: 130), spacing: 8)], alignment: .leading, spacing: 8) {
            ForEach(available) { chain in
                let isOn = settings.selectedChainIDs.contains(chain.id)
                Button {
                    toggleChain(chain.id)
                } label: {
                    HStack(spacing: 5) {
                        Image(systemName: isOn ? "checkmark.circle.fill" : "circle")
                            .font(.system(size: 10))
                        Text(chain.name)
                            .font(.caption)
                            .lineLimit(1)
                    }
                    .padding(.horizontal, 9)
                    .padding(.vertical, 5)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(
                        Capsule().fill(isOn ? Palette.accent.opacity(0.18) : Color.primary.opacity(0.05))
                    )
                    .foregroundStyle(isOn ? Palette.accent : Palette.ink)
                }
                .buttonStyle(.plain)
                .help(chain.isRegional
                      ? "\(chain.name) — региональная сеть, есть не во всех городах страны"
                      : chain.name)
            }
        }
        .frame(maxWidth: 420)
    }

    // MARK: Итоги

    private var summaryTiles: some View {
        let current = plan
        let cheapest = current.cheapestSingle
        let perPerson = current.household.peopleCount > 0
            ? current.splitTotal / Double(current.household.peopleCount)
            : 0
        return LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 12), count: 4), spacing: 12) {
            StatTile(
                icon: "cart.fill",
                title: "Дешевле всего в одном магазине",
                value: Fmt.money(cheapest?.total ?? 0, code: current.currency),
                caption: cheapest?.chain.name ?? "—",
                tint: Palette.green
            )
            StatTile(
                icon: "arrow.triangle.branch",
                title: "Если разделить по категориям",
                value: Fmt.money(current.splitTotal, code: current.currency),
                caption: current.splitSaving > 0
                    ? "экономия \(Fmt.money(current.splitSaving, code: current.currency)) в месяц"
                    : "разделять смысла нет",
                tint: Palette.accent
            )
            StatTile(
                icon: "arrow.up.arrow.down",
                title: "Разброс между сетями",
                value: Fmt.money(current.chainSpread, code: current.currency),
                caption: "между самой дешёвой и самой дорогой сетью",
                tint: Palette.amber
            )
            StatTile(
                icon: "person.2.fill",
                title: "На человека в месяц",
                value: Fmt.money(perPerson, code: current.currency),
                caption: current.household.title,
                tint: Palette.teal
            )
        }
    }

    // MARK: Сравнение сетей

    private var chainsCard: some View {
        let current = plan
        return VStack(alignment: .leading, spacing: 12) {
            SectionTitle(
                title: "Вся корзина в каждой сети",
                subtitle: "\(current.city.name) · \(current.itemsCount) позиций · \(current.household.title)"
            )
            Chart {
                ForEach(current.chainTotals) { item in
                    BarMark(
                        x: .value("Сумма", item.total),
                        y: .value("Сеть", item.chain.name)
                    )
                    .foregroundStyle(item.id == current.cheapestSingle?.id ? Palette.green : Palette.accent.opacity(0.75))
                    .cornerRadius(4)
                    .annotation(position: .trailing) {
                        Text(Fmt.money(item.total, code: current.currency))
                            .font(.caption2)
                            .foregroundStyle(Palette.muted)
                    }
                }
            }
            .frame(height: max(CGFloat(current.chainTotals.count) * 30 + 30, 120))
        }
        .cardStyle()
    }

    // MARK: Оптимальный сплит

    private var splitCard: some View {
        let current = plan
        return VStack(alignment: .leading, spacing: 12) {
            SectionTitle(
                title: "Где что брать",
                subtitle: "по каждой категории — сеть с самой низкой суммой из выбранных"
            )

            Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 8) {
                GridRow {
                    Text("Категория").gridColumnAlignment(.leading)
                    Text("Магазин").gridColumnAlignment(.leading)
                    Text("В месяц").gridColumnAlignment(.trailing)
                    Text("Переплата в худшей сети").gridColumnAlignment(.trailing)
                }
                .font(.caption.weight(.semibold))
                .foregroundStyle(Palette.muted)

                Divider().gridCellUnsizedAxes(.horizontal)

                ForEach(current.categoryWinners) { winner in
                    GridRow {
                        Text("\(winner.category.emoji) \(winner.category.title)")
                            .font(.subheadline)
                        Text(winner.chain.name)
                            .font(.subheadline.weight(.medium))
                            .foregroundStyle(Palette.accent)
                        Text(Fmt.money(winner.total, code: current.currency))
                            .font(.subheadline.monospacedDigit())
                        Text(winner.spread > 0.5 ? "+\(Fmt.money(winner.spread, code: current.currency))" : "—")
                            .font(.subheadline.monospacedDigit())
                            .foregroundStyle(winner.spread > 0.5 ? Palette.amber : Palette.muted)
                    }
                }
            }

            if current.splitSaving > 0 {
                Text("Разделить покупки между \(Set(current.categoryWinners.map { $0.chain.id }).count) магазинами выгоднее одного самого дешёвого на \(Fmt.money(current.splitSaving, code: current.currency)) в месяц — примерно \(Fmt.money(current.splitSaving * 12, code: current.currency)) в год.")
                    .font(.caption)
                    .foregroundStyle(Palette.muted)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .cardStyle()
    }

    // MARK: Сверка с фактом

    @ViewBuilder
    private var factCard: some View {
        let ids = store.analytics.categoryIDs(named: ["Продукты"])
        let fact = ids.isEmpty ? 0 : store.analytics.averageMonthlySpend(categoryIDs: ids, months: 3)
        if fact > 0 {
            let estimate = plan.splitTotal
            let delta = fact - estimate
            VStack(alignment: .leading, spacing: 10) {
                SectionTitle(
                    title: "Корзина против вашего факта",
                    subtitle: "средний расход по категории «Продукты» за последние месяцы"
                )
                HStack(spacing: 26) {
                    KeyValueRow(key: "Корзина по модели", value: Fmt.money(estimate, code: plan.currency), bold: true)
                    KeyValueRow(key: "Факт в месяц", value: Fmt.money(fact, code: store.currency), bold: true)
                    KeyValueRow(
                        key: delta >= 0 ? "Сверх корзины" : "Ниже корзины",
                        value: Fmt.money(abs(delta), code: store.currency),
                        valueColor: delta > 0 ? Palette.amber : Palette.green
                    )
                }
                Text(delta > 0
                     ? "Разница — это доставки, готовая еда, спонтанные покупки и всё, что не входит в базовую корзину. Именно она обычно и съедает темп накоплений."
                     : "Вы укладываетесь в базовую корзину — по продуктам резерва почти нет, искать экономию стоит в других категориях.")
                    .font(.caption)
                    .foregroundStyle(Palette.muted)
                    .fixedSize(horizontal: false, vertical: true)
                if plan.currency != store.currency {
                    Text("Валюта корзины (\(plan.currency)) не совпадает с валютой учёта (\(store.currency)) — суммы не переводятся по курсу.")
                        .font(.caption2)
                        .foregroundStyle(Palette.amber)
                }
            }
            .cardStyle()
        }
    }

    // MARK: Список продуктов

    private var productsCard: some View {
        let current = plan
        return VStack(alignment: .leading, spacing: 14) {
            SectionTitle(
                title: "Что входит в корзину",
                subtitle: "количество на месяц для этой семьи · нажмите на строку, чтобы поправить цены"
            )

            ForEach(BasketCategory.allCases) { category in
                let lines = current.lines(in: category)
                if !lines.isEmpty {
                    VStack(alignment: .leading, spacing: 6) {
                        HStack {
                            Text("\(category.emoji) \(category.title)")
                                .font(.subheadline.weight(.semibold))
                            Spacer()
                            Text(Fmt.money(current.categoryTotal(category), code: current.currency))
                                .font(.subheadline.monospacedDigit())
                                .foregroundStyle(Palette.muted)
                        }
                        ForEach(lines) { line in
                            basketRow(line: line, plan: current)
                        }
                    }
                    .padding(.bottom, 4)
                }
            }
        }
        .cardStyle()
    }

    private func basketRow(line: BasketLine, plan: BasketPlan) -> some View {
        let chainName = line.bestChainID.flatMap { plan.chain(id: $0)?.name } ?? "—"
        let isManual = line.bestChainID.map { line.manual.contains($0) } ?? false
        return HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 1) {
                Text(line.product.name)
                    .font(.body)
                Text("\(quantityText(line.quantity)) × \(line.product.unit)")
                    .font(.caption)
                    .foregroundStyle(Palette.muted)
            }

            Spacer(minLength: 8)

            Text(chainName)
                .font(.caption)
                .padding(.horizontal, 7)
                .padding(.vertical, 3)
                .background(Capsule().fill(Palette.accent.opacity(0.12)))
                .foregroundStyle(Palette.accent)

            HStack(spacing: 4) {
                if isManual {
                    Image(systemName: "pencil")
                        .font(.system(size: 9))
                        .foregroundStyle(Palette.teal)
                }
                Text(Fmt.money(line.bestUnitPrice, code: plan.currency, fraction: true))
                    .font(.caption.monospacedDigit())
                    .foregroundStyle(Palette.muted)
            }
            .frame(width: 80, alignment: .trailing)

            Text(Fmt.money(line.bestTotal, code: plan.currency))
                .font(.subheadline.monospacedDigit().weight(.medium))
                .frame(width: 78, alignment: .trailing)

            Button {
                toggleExcluded(line.product.id)
            } label: {
                Image(systemName: "minus.circle")
            }
            .buttonStyle(.borderless)
            .help("Убрать товар из корзины")
        }
        .padding(.vertical, 2)
        .contentShape(Rectangle())
        .onTapGesture { editingProductID = line.product.id }
    }

    private func quantityText(_ value: Double) -> String {
        let rounded = (value * 10).rounded() / 10
        if abs(rounded - rounded.rounded()) < 0.05 {
            return String(Int(rounded.rounded()))
        }
        return String(format: "%.1f", rounded)
    }

    // MARK: Оговорка про источник цен

    private var sourceNote: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label("Откуда цены", systemImage: "info.circle")
                .font(.subheadline.weight(.semibold))
            Text("Это модель-ориентир, а не выгрузка из магазинов: справочная полочная цена умножается на уровень города и уровень сети по категории. Справочник пересматривался вручную — \(BasketCatalog.updatedAt). Приложение никуда не ходит по сети.")
                .font(.caption)
                .foregroundStyle(Palette.muted)
                .fixedSize(horizontal: false, vertical: true)
            Text("Список сетей зависит от города: региональные сети (Eroski и BM на севере, Consum в Леванте) показываются только там, где они действительно работают. Присутствие указано приблизительно, по крупным форматам.")
                .font(.caption)
                .foregroundStyle(Palette.muted)
                .fixedSize(horizontal: false, vertical: true)
            Text("Любую цену можно поправить: нажмите на строку товара и введите то, что видите на полке. Ваша цена перебивает модель, помечается карандашом и сохраняется в данных.")
                .font(.caption)
                .foregroundStyle(Palette.muted)
                .fixedSize(horizontal: false, vertical: true)

            if !settings.excludedProductIDs.isEmpty {
                HStack {
                    Text("Убрано из корзины: \(settings.excludedProductIDs.count)")
                        .font(.caption)
                        .foregroundStyle(Palette.muted)
                    Button("Вернуть всё") { store.data.basket.excludedProductIDs = [] }
                        .buttonStyle(.link)
                }
            }
            if !settings.priceOverrides.isEmpty {
                HStack {
                    Text("Своих цен: \(settings.priceOverrides.count)")
                        .font(.caption)
                        .foregroundStyle(Palette.muted)
                    Button("Сбросить к модели") { store.data.basket.priceOverrides = [:] }
                        .buttonStyle(.link)
                }
            }
        }
        .cardStyle()
    }

    // MARK: Действия

    private var countryBinding: Binding<String> {
        Binding(
            get: { store.data.basket.countryID },
            set: { newValue in
                store.data.basket.countryID = newValue
                // Город и сети принадлежат стране — при смене страны сбрасываем их.
                store.data.basket.cityID = BasketCatalog.country(id: newValue).cities.first?.id ?? ""
                store.data.basket.selectedChainIDs = []
            }
        )
    }

    private func toggleChain(_ id: String) {
        var selected = store.data.basket.selectedChainIDs
        if let index = selected.firstIndex(of: id) {
            selected.remove(at: index)
        } else {
            selected.append(id)
        }
        store.data.basket.selectedChainIDs = selected
    }

    private func toggleExcluded(_ id: String) {
        var excluded = store.data.basket.excludedProductIDs
        if let index = excluded.firstIndex(of: id) {
            excluded.remove(at: index)
        } else {
            excluded.append(id)
        }
        store.data.basket.excludedProductIDs = excluded
    }

    /// Обёртка, чтобы открывать лист по строковому идентификатору товара.
    private struct EditingProduct: Identifiable {
        let id: String
    }

    private var editingProductBinding: Binding<EditingProduct?> {
        Binding(
            get: { editingProductID.map { EditingProduct(id: $0) } },
            set: { editingProductID = $0?.id }
        )
    }
}

// MARK: - Редактор цен товара

struct BasketPriceEditor: View {
    @EnvironmentObject private var store: Store
    @Environment(\.dismiss) private var dismiss

    var productID: String

    private var product: BasketProduct? { BasketCatalog.product(id: productID) }
    private var plan: BasketPlan { BasketPlanner.plan(settings: store.data.basket) }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if let product = product {
                header(product)

                Form {
                    Section("Цена за \(product.unit)") {
                        ForEach(plan.chains) { chain in
                            HStack {
                                Text(chain.name)
                                Spacer()
                                if isManual(chain: chain, product: product) {
                                    Button {
                                        reset(chain: chain, product: product)
                                    } label: {
                                        Image(systemName: "arrow.uturn.backward")
                                    }
                                    .buttonStyle(.borderless)
                                    .help("Вернуть цену из модели")
                                }
                                AmountField(
                                    title: "0",
                                    value: priceBinding(chain: chain, product: product),
                                    currency: plan.currency
                                )
                                .frame(width: 130)
                            }
                        }
                    }

                    Section {
                        Text("Введённая цена сохранится и будет использоваться вместо модельной для этого товара в этой сети.")
                            .font(.caption)
                            .foregroundStyle(Palette.muted)
                    }
                }
                .formStyle(.grouped)
            } else {
                Text("Товар не найден")
                    .padding()
            }

            HStack {
                Spacer()
                Button("Готово") { dismiss() }
                    .buttonStyle(.borderedProminent)
                    .keyboardShortcut(.defaultAction)
            }
            .padding(20)
        }
        .frame(width: 460)
    }

    private func header(_ product: BasketProduct) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text("\(product.category.emoji) \(product.name)")
                .font(.headline)
            Text("\(plan.city.name) · цены за \(product.unit)")
                .font(.caption)
                .foregroundStyle(Palette.muted)
        }
        .padding(.horizontal, 20)
        .padding(.top, 18)
    }

    private func isManual(chain: StoreChain, product: BasketProduct) -> Bool {
        store.data.basket.priceOverrides[BasketSettings.overrideKey(chainID: chain.id, productID: product.id)] != nil
    }

    private func reset(chain: StoreChain, product: BasketProduct) {
        store.data.basket.priceOverrides.removeValue(
            forKey: BasketSettings.overrideKey(chainID: chain.id, productID: product.id)
        )
    }

    private func priceBinding(chain: StoreChain, product: BasketProduct) -> Binding<Double> {
        let key = BasketSettings.overrideKey(chainID: chain.id, productID: product.id)
        let city = plan.city
        return Binding(
            get: {
                BasketPlanner.unitPrice(
                    product: product,
                    chain: chain,
                    city: city,
                    overrides: store.data.basket.priceOverrides
                ).value
            },
            set: { newValue in
                if newValue > 0 {
                    store.data.basket.priceOverrides[key] = (newValue * 100).rounded() / 100
                } else {
                    store.data.basket.priceOverrides.removeValue(forKey: key)
                }
            }
        )
    }
}
