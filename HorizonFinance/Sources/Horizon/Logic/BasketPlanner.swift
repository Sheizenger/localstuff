import Foundation

struct BasketLine: Identifiable {
    let product: BasketProduct
    let quantity: Double
    /// Цена за единицу по каждой рассматриваемой сети.
    let prices: [String: Double]
    /// Сети, где цену ввели руками.
    let manual: Set<String>
    let bestChainID: String?

    var id: String { product.id }

    var bestUnitPrice: Double {
        guard let best = bestChainID, let price = prices[best] else { return 0 }
        return price
    }

    var bestTotal: Double { bestUnitPrice * quantity }

    func total(in chainID: String) -> Double {
        (prices[chainID] ?? 0) * quantity
    }
}

struct ChainTotal: Identifiable {
    let chain: StoreChain
    let total: Double
    var id: String { chain.id }
}

struct CategoryWinner: Identifiable {
    let category: BasketCategory
    let chain: StoreChain
    let total: Double
    /// Насколько дороже вышло бы в самой дорогой из рассматриваемых сетей.
    let spread: Double
    var id: String { category.rawValue }
}

struct BasketPlan {
    let country: BasketCountry
    let city: BasketCity
    let chains: [StoreChain]
    let household: Household
    let lines: [BasketLine]
    /// Стоимость всей корзины в каждой сети, от дешёвой к дорогой.
    let chainTotals: [ChainTotal]
    /// Где выгоднее брать каждую категорию.
    let categoryWinners: [CategoryWinner]

    var currency: String { country.currencyCode }
    var cheapestSingle: ChainTotal? { chainTotals.first }
    var dearestSingle: ChainTotal? { chainTotals.last }

    /// Итог, если каждую категорию покупать там, где она дешевле.
    var splitTotal: Double { categoryWinners.reduce(0.0) { $0 + $1.total } }

    /// Сколько даёт разделение покупок по сравнению с одним самым дешёвым магазином.
    var splitSaving: Double { max((cheapestSingle?.total ?? 0) - splitTotal, 0) }

    /// Разница между самым дешёвым и самым дорогим вариантом «всё в одном магазине».
    var chainSpread: Double { (dearestSingle?.total ?? 0) - (cheapestSingle?.total ?? 0) }

    var itemsCount: Int { lines.count }

    /// Сумма по методике статистики: еда и безалкогольные напитки,
    /// без бытовой химии, гигиены и алкоголя. Только так корзину можно сравнивать с INE.
    var foodAndSoftDrinksTotal: Double {
        lines
            .filter { $0.product.category != .household && $0.product.id != "alcohol" }
            .reduce(0.0) { $0 + $1.bestTotal }
    }

    func categoryTotal(_ category: BasketCategory) -> Double {
        categoryWinners.first(where: { $0.category == category })?.total ?? 0
    }

    func lines(in category: BasketCategory) -> [BasketLine] {
        lines.filter { $0.product.category == category }
    }

    func chain(id: String) -> StoreChain? {
        chains.first(where: { $0.id == id })
    }
}

enum BasketPlanner {

    /// Сколько единиц товара нужно семье в месяц.
    static func quantity(for product: BasketProduct, household: Household) -> Double {
        var total = 0.0

        if product.onlyForAges.isEmpty {
            // Еду второй взрослый ест наравне с первым, а вот бытовая химия и хозтовары
            // делятся на всех — экономия от общего хозяйства только здесь.
            let scale = product.category == .household ? 0.75 : 1.0
            for index in 0..<max(household.adults, 0) {
                total += product.perAdult * (index == 0 ? 1.0 : scale)
            }
            for child in household.children {
                total += product.perChild * child.factor
            }
        } else {
            for child in household.children where product.onlyForAges.contains(child) {
                total += product.perChild
            }
        }

        return (total * 100).rounded() / 100
    }

    /// Цена за единицу: ручная цена важнее модели.
    static func unitPrice(
        product: BasketProduct,
        chain: StoreChain,
        city: BasketCity,
        overrides: [String: Double]
    ) -> (value: Double, isManual: Bool) {
        let key = BasketSettings.overrideKey(chainID: chain.id, productID: product.id)
        if let manual = overrides[key], manual > 0 {
            return (manual, true)
        }
        let modelled = product.basePrice * city.index * chain.index(for: product.category)
        return (((modelled * 100).rounded() / 100), false)
    }

    static func plan(settings: BasketSettings) -> BasketPlan {
        let country = BasketCatalog.country(id: settings.countryID)
        let city = BasketCatalog.city(countryID: settings.countryID, cityID: settings.cityID)
        let household = settings.household

        // Сначала отсекаем сети, которых в этом городе нет, и только потом применяем выбор.
        var chains = BasketCatalog.availableChains(countryID: settings.countryID, cityID: city.id)
        if !settings.selectedChainIDs.isEmpty {
            let picked = chains.filter { settings.selectedChainIDs.contains($0.id) }
            if !picked.isEmpty { chains = picked }
        }

        let excluded = Set(settings.excludedProductIDs)
        var lines: [BasketLine] = []

        for product in BasketCatalog.products where !excluded.contains(product.id) {
            let qty = quantity(for: product, household: household)
            guard qty > 0.001 else { continue }

            var prices: [String: Double] = [:]
            var manual: Set<String> = []
            for chain in chains {
                let price = unitPrice(product: product, chain: chain, city: city, overrides: settings.priceOverrides)
                prices[chain.id] = price.value
                if price.isManual { manual.insert(chain.id) }
            }

            // Самая дешёвая сеть для этого товара; при равенстве — первая по порядку в справочнике.
            var bestID: String? = nil
            var bestValue = Double.greatestFiniteMagnitude
            for chain in chains {
                guard let price = prices[chain.id] else { continue }
                if price < bestValue - 0.0001 {
                    bestValue = price
                    bestID = chain.id
                }
            }

            lines.append(
                BasketLine(product: product, quantity: qty, prices: prices, manual: manual, bestChainID: bestID)
            )
        }

        let chainTotals = chains
            .map { chain in
                ChainTotal(chain: chain, total: lines.reduce(0.0) { $0 + $1.total(in: chain.id) })
            }
            .sorted { $0.total < $1.total }

        var winners: [CategoryWinner] = []
        for category in BasketCategory.allCases {
            let categoryLines = lines.filter { $0.product.category == category }
            guard !categoryLines.isEmpty else { continue }

            var bestChain: StoreChain? = nil
            var bestTotal = Double.greatestFiniteMagnitude
            var worstTotal = 0.0
            for chain in chains {
                let total = categoryLines.reduce(0.0) { $0 + $1.total(in: chain.id) }
                if total < bestTotal - 0.0001 {
                    bestTotal = total
                    bestChain = chain
                }
                worstTotal = max(worstTotal, total)
            }
            if let bestChain = bestChain {
                winners.append(
                    CategoryWinner(category: category, chain: bestChain, total: bestTotal, spread: worstTotal - bestTotal)
                )
            }
        }

        return BasketPlan(
            country: country,
            city: city,
            chains: chains,
            household: household,
            lines: lines,
            chainTotals: chainTotals,
            categoryWinners: winners
        )
    }
}
