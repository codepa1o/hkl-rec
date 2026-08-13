import * as d3 from "d3";
import { useEffect, useMemo, useRef } from "react";
import type { ProfileTopicWeight } from "../api/types";

interface Props {
  topicWeights: ProfileTopicWeight[];
  limit?: number;
}

interface ChartDatum {
  topicId: number;
  label: string;
  weight: number;
}

const WIDTH = 272;
const BAR_HEIGHT = 22;
const MARGIN = { top: 8, right: 42, bottom: 24, left: 64 };

export default function TopicWeightChart({ topicWeights, limit = 8 }: Props) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const chartData = useMemo<ChartDatum[]>(
    () =>
      [...topicWeights]
        .sort((a, b) => b.weight - a.weight)
        .slice(0, limit)
        .map((item) => ({
          topicId: item.topic_id,
          label: `主题${item.topic_id}`,
          weight: item.weight,
        })),
    [topicWeights, limit],
  );

  useEffect(() => {
    if (!svgRef.current || chartData.length === 0) return;

    const height = MARGIN.top + MARGIN.bottom + chartData.length * BAR_HEIGHT;
    const innerWidth = WIDTH - MARGIN.left - MARGIN.right;
    const innerHeight = height - MARGIN.top - MARGIN.bottom;
    const maxWeight = d3.max(chartData, (d) => d.weight) ?? 0;

    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();
    svg.attr("viewBox", `0 0 ${WIDTH} ${height}`);

    const x = d3
      .scaleLinear()
      .domain([0, Math.max(maxWeight * 1.1, 0.01)])
      .range([0, innerWidth])
      .nice();

    const y = d3
      .scaleBand<string>()
      .domain(chartData.map((d) => d.label))
      .range([0, innerHeight])
      .padding(0.28);

    const root = svg
      .append("g")
      .attr("class", "zr-topic-chart__plot")
      .attr("transform", `translate(${MARGIN.left},${MARGIN.top})`);

    root
      .append("g")
      .attr("class", "zr-topic-chart__axis zr-topic-chart__axis--y")
      .call(d3.axisLeft(y).tickSize(0))
      .call((g) => g.select(".domain").remove());

    root
      .append("g")
      .attr("class", "zr-topic-chart__axis zr-topic-chart__axis--x")
      .attr("transform", `translate(0,${innerHeight})`)
      .call(d3.axisBottom(x).ticks(3).tickSizeOuter(0));

    const bars = root
      .append("g")
      .attr("class", "zr-topic-chart__bars")
      .selectAll<SVGGElement, ChartDatum>("g")
      .data(chartData, (d) => String(d.topicId))
      .join("g")
      .attr("transform", (d) => `translate(0,${y(d.label) ?? 0})`);

    bars
      .append("rect")
      .attr("class", "zr-topic-chart__bar-bg")
      .attr("width", innerWidth)
      .attr("height", y.bandwidth())
      .attr("rx", 3);

    bars
      .append("rect")
      .attr("class", "zr-topic-chart__bar")
      .attr("width", (d) => x(d.weight))
      .attr("height", y.bandwidth())
      .attr("rx", 3);

    bars
      .append("text")
      .attr("class", "zr-topic-chart__value")
      .attr("x", (d) => Math.min(x(d.weight) + 5, innerWidth + 4))
      .attr("y", y.bandwidth() / 2)
      .attr("dominant-baseline", "middle")
      .text((d) => d.weight.toFixed(2));
  }, [chartData]);

  if (chartData.length === 0) {
    return <div className="zr-topic-chart__empty">暂无主题信号</div>;
  }

  return (
    <div className="zr-topic-chart" aria-label="主题权重柱状图">
      <svg ref={svgRef} role="img" />
    </div>
  );
}
