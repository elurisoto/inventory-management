<template>
  <div class="restocking">
    <div class="page-header">
      <h2>{{ t('restocking.title') }}</h2>
      <p>{{ t('restocking.description') }}</p>
    </div>

    <div v-if="loading" class="loading">{{ t('common.loading') }}</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else>
      <!-- Budget Control -->
      <div class="card budget-card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.availableBudget') }}</h3>
        </div>
        <div class="budget-control">
          <input
            type="range"
            v-model.number="budget"
            :min="0"
            :max="budgetMax"
            :step="500"
            class="budget-slider"
          />
          <div class="budget-display">
            {{ currencySymbol }}{{ budget.toLocaleString() }}
          </div>
        </div>
      </div>

      <!-- Summary Stats -->
      <div class="stats-grid">
        <div class="stat-card info">
          <div class="stat-label">{{ t('restocking.recommended') }}</div>
          <div class="stat-value">{{ t('restocking.recommendedCount', { count: selectedSkus.size }) }}</div>
        </div>
        <div class="stat-card warning">
          <div class="stat-label">{{ t('restocking.estimatedCost') }}</div>
          <div class="stat-value">{{ currencySymbol }}{{ totalCost.toLocaleString() }}</div>
        </div>
        <div :class="['stat-card', remaining < 0 ? 'danger' : 'success']">
          <div class="stat-label">{{ t('restocking.remainingBudget') }}</div>
          <div class="stat-value">{{ currencySymbol }}{{ remaining.toLocaleString() }}</div>
        </div>
      </div>

      <!-- Forecast Table -->
      <div class="card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.title') }}</h3>
        </div>
        <div class="table-container">
          <table class="restocking-table">
            <thead>
              <tr>
                <th class="col-include">{{ t('restocking.table.include') }}</th>
                <th class="col-sku">{{ t('restocking.table.sku') }}</th>
                <th class="col-name">{{ t('restocking.table.itemName') }}</th>
                <th class="col-trend">{{ t('restocking.table.trend') }}</th>
                <th class="col-demand">{{ t('restocking.table.forecastedDemand') }}</th>
                <th class="col-cost">{{ t('restocking.table.unitCost') }}</th>
                <th class="col-line">{{ t('restocking.table.lineCost') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="item in sortedForecasts"
                :key="item.item_sku"
                :class="{ 'row-selected': selectedSkus.has(item.item_sku) }"
              >
                <td class="col-include">
                  <input
                    type="checkbox"
                    :checked="selectedSkus.has(item.item_sku)"
                    @change="toggleItem(item.item_sku)"
                    class="row-checkbox"
                  />
                </td>
                <td class="col-sku"><strong>{{ item.item_sku }}</strong></td>
                <td class="col-name">{{ item.item_name }}</td>
                <td class="col-trend">
                  <span :class="['badge', item.trend]">
                    {{ t(`trends.${item.trend}`) }}
                  </span>
                </td>
                <td class="col-demand">{{ item.forecasted_demand }}</td>
                <td class="col-cost">{{ currencySymbol }}{{ item.unit_cost.toLocaleString() }}</td>
                <td class="col-line"><strong>{{ currencySymbol }}{{ getLineCost(item).toLocaleString() }}</strong></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Place Order -->
      <div class="order-action">
        <div v-if="orderSuccess" class="order-success">
          {{ t('restocking.orderPlaced', { orderNumber: orderSuccess }) }}
        </div>
        <div v-if="orderError" class="error">{{ orderError }}</div>
        <p v-if="selectedSkus.size === 0" class="no-selection-hint">
          {{ t('restocking.noSelection') }}
        </p>
        <button
          class="btn-place-order"
          :disabled="selectedSkus.size === 0 || remaining < 0 || placing"
          @click="placeOrder"
        >
          {{ placing ? t('restocking.placingOrder') : t('restocking.placeOrder') }}
        </button>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, watch, onMounted } from 'vue'
import { api } from '../api'
import { useI18n } from '../composables/useI18n'

const TREND_ORDER = { increasing: 0, stable: 1, decreasing: 2 }

export default {
  name: 'Restocking',
  setup() {
    const { t, currentCurrency } = useI18n()

    const currencySymbol = computed(() => {
      return currentCurrency.value === 'JPY' ? '¥' : '$'
    })

    const loading = ref(true)
    const error = ref(null)
    const forecasts = ref([])

    const budget = ref(0)
    const budgetMax = ref(0)

    const selectedSkus = ref(new Set())

    const placing = ref(false)
    const orderSuccess = ref(null)
    const orderError = ref(null)

    // Sorted by priority: increasing → stable → decreasing, tie-break by forecasted_demand desc
    const sortedForecasts = computed(() => {
      return [...forecasts.value].sort((a, b) => {
        const trendDiff = (TREND_ORDER[a.trend] ?? 3) - (TREND_ORDER[b.trend] ?? 3)
        if (trendDiff !== 0) return trendDiff
        return b.forecasted_demand - a.forecasted_demand
      })
    })

    const getLineCost = (item) => {
      return item.forecasted_demand * item.unit_cost
    }

    const totalCost = computed(() => {
      let sum = 0
      for (const item of forecasts.value) {
        if (selectedSkus.value.has(item.item_sku)) {
          sum += getLineCost(item)
        }
      }
      return sum
    })

    const remaining = computed(() => budget.value - totalCost.value)

    // Greedy recommendation: iterate priority-sorted items, include if fits remaining budget
    const computeRecommended = () => {
      const items = sortedForecasts.value
      let remaining = budget.value
      const recommended = new Set()
      for (const item of items) {
        const cost = getLineCost(item)
        if (cost <= remaining) {
          recommended.add(item.item_sku)
          remaining -= cost
        }
      }
      selectedSkus.value = recommended
    }

    watch(budget, () => {
      computeRecommended()
    })

    const toggleItem = (sku) => {
      const next = new Set(selectedSkus.value)
      if (next.has(sku)) {
        next.delete(sku)
      } else {
        next.add(sku)
      }
      selectedSkus.value = next
    }

    const loadForecasts = async () => {
      try {
        loading.value = true
        error.value = null
        const data = await api.getDemandForecasts()
        forecasts.value = data

        // Compute max budget: ceiling of total all line costs, rounded up to nearest 1000
        const totalAll = data.reduce((sum, item) => sum + item.forecasted_demand * item.unit_cost, 0)
        const maxRounded = Math.ceil(totalAll / 1000) * 1000
        budgetMax.value = maxRounded

        // Default budget to ~40% of max
        budget.value = Math.round((maxRounded * 0.4) / 500) * 500

        // Initialize recommendation
        computeRecommended()
      } catch (err) {
        error.value = t('common.error') + ': ' + err.message
        console.error(err)
      } finally {
        loading.value = false
      }
    }

    const placeOrder = async () => {
      orderSuccess.value = null
      orderError.value = null
      placing.value = true
      try {
        const items = sortedForecasts.value
          .filter(item => selectedSkus.value.has(item.item_sku))
          .map(item => ({
            sku: item.item_sku,
            name: item.item_name,
            quantity: item.forecasted_demand,
            unit_cost: item.unit_cost
          }))
        const result = await api.createRestockingOrder({ budget: budget.value, items })
        orderSuccess.value = result.order_number
        // Clear selection after successful order
        selectedSkus.value = new Set()
      } catch (err) {
        orderError.value = err.response?.data?.detail || err.message || 'Failed to place order'
        console.error(err)
      } finally {
        placing.value = false
      }
    }

    onMounted(loadForecasts)

    return {
      t,
      currencySymbol,
      loading,
      error,
      sortedForecasts,
      budget,
      budgetMax,
      selectedSkus,
      totalCost,
      remaining,
      placing,
      orderSuccess,
      orderError,
      getLineCost,
      toggleItem,
      placeOrder
    }
  }
}
</script>

<style scoped>
.restocking {
  /* page container, inherits main-content padding */
}

.budget-card {
  margin-bottom: 1.25rem;
}

.budget-control {
  display: flex;
  align-items: center;
  gap: 1.5rem;
  padding: 0.5rem 0;
}

.budget-slider {
  flex: 1;
  height: 6px;
  appearance: none;
  background: #e2e8f0;
  border-radius: 3px;
  outline: none;
  cursor: pointer;
}

.budget-slider::-webkit-slider-thumb {
  appearance: none;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #2563eb;
  cursor: pointer;
  border: 2px solid white;
  box-shadow: 0 0 0 1px #2563eb;
}

.budget-slider::-moz-range-thumb {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #2563eb;
  cursor: pointer;
  border: 2px solid white;
}

.budget-display {
  font-size: 1.5rem;
  font-weight: 700;
  color: #0f172a;
  min-width: 160px;
  text-align: right;
  letter-spacing: -0.025em;
}

/* Table */
.restocking-table {
  table-layout: fixed;
  width: 100%;
}

.col-include {
  width: 60px;
  text-align: center;
}

.col-sku {
  width: 120px;
}

.col-name {
  width: auto;
}

.col-trend {
  width: 120px;
}

.col-demand {
  width: 130px;
  text-align: right;
}

.col-cost {
  width: 110px;
  text-align: right;
}

.col-line {
  width: 130px;
  text-align: right;
}

.row-checkbox {
  width: 16px;
  height: 16px;
  cursor: pointer;
  accent-color: #2563eb;
}

/* Highlighted selected row */
.row-selected {
  background: #eff6ff !important;
}

.row-selected:hover {
  background: #dbeafe !important;
}

/* Order action area */
.order-action {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 0.75rem;
  margin-top: 1rem;
  padding-top: 0.5rem;
}

.no-selection-hint {
  font-size: 0.875rem;
  color: #64748b;
}

.btn-place-order {
  padding: 0.75rem 2rem;
  background: #2563eb;
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 0.938rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s ease;
}

.btn-place-order:hover:not(:disabled) {
  background: #1d4ed8;
}

.btn-place-order:disabled {
  background: #94a3b8;
  cursor: not-allowed;
}

.order-success {
  padding: 0.875rem 1.25rem;
  background: #d1fae5;
  border: 1px solid #6ee7b7;
  border-radius: 8px;
  color: #065f46;
  font-weight: 500;
  font-size: 0.938rem;
  width: 100%;
  text-align: center;
}
</style>
