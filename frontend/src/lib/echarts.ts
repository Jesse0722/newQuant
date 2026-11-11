import { use as registerCharts } from 'echarts/core'
import { BarChart, CandlestickChart, LineChart } from 'echarts/charts'
import { AxisPointerComponent, DataZoomComponent, GridComponent, LegendComponent, MarkLineComponent, MarkPointComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

registerCharts([BarChart, CandlestickChart, LineChart, AxisPointerComponent, DataZoomComponent, GridComponent, LegendComponent, MarkLineComponent, MarkPointComponent, TooltipComponent, CanvasRenderer])
export * from 'echarts/core'
export type { EChartsOption } from 'echarts'
