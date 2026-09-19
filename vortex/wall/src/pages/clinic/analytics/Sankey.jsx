import { useMemo, useState } from "react";

/* A Sankey drawn by hand.

   The wall ships no chart library on purpose (see vortex/wall/README.md), and
   a three-column flow needs about sixty lines of layout, so here it is rather
   than a dependency. Nodes are laid out per column, heights are proportional
   to their value, and each link is a cubic between the right edge of its
   source and the left edge of its target, stacked in the order the nodes sit
   in so ribbons never cross inside one band.

   Colour never appears here: every node carries a `tone` the stylesheet maps
   to a design token. */

const WIDTH = 1000;
const HEIGHT = 440;
const NODE_W = 13;
const GAP = 9;
const PAD_TOP = 8;
const LABEL_GAP = 12;

function layout(nodes, links) {
  const columns = [...new Set(nodes.map((n) => n.column))].sort((a, b) => a - b);
  const lastColumn = columns[columns.length - 1];
  const placed = new Map();

  columns.forEach((column) => {
    const inColumn = nodes.filter((n) => n.column === column);
    const total = inColumn.reduce((sum, n) => sum + n.value, 0) || 1;
    // Every column represents the same population, so they share one scale —
    // that is the whole point of the picture. The gaps are taken out first so
    // a column of twelve nodes still adds up to the same height as one node.
    const usable = HEIGHT - PAD_TOP * 2 - GAP * Math.max(inColumn.length - 1, 0);
    let y = PAD_TOP;
    inColumn.forEach((node) => {
      const h = Math.max((node.value / total) * usable, 2);
      placed.set(node.id, {
        ...node,
        x: (column / lastColumn) * (WIDTH - NODE_W - 300),
        y,
        h,
        // Ribbons stack from the top of each side as they are drawn.
        outAt: y,
        inAt: y,
      });
      y += h + GAP;
    });
  });

  const ribbons = links
    .map((link) => ({ ...link, a: placed.get(link.source), b: placed.get(link.target) }))
    .filter((link) => link.a && link.b)
    .sort((p, q) => p.a.y - q.a.y || p.b.y - q.b.y);

  const paths = ribbons.map((link) => {
    const { a, b } = link;
    const columnTotalA = a.value || 1;
    const columnTotalB = b.value || 1;
    const ha = (link.value / columnTotalA) * a.h;
    const hb = (link.value / columnTotalB) * b.h;
    const y0 = a.outAt;
    const y1 = b.inAt;
    a.outAt += ha;
    b.inAt += hb;

    const x0 = a.x + NODE_W;
    const x1 = b.x;
    const mid = x0 + (x1 - x0) / 2;
    return {
      id: `${link.source}->${link.target}`,
      source: link.source,
      target: link.target,
      value: link.value,
      tone: b.tone,
      d: [
        `M${x0},${y0}`,
        `C${mid},${y0} ${mid},${y1} ${x1},${y1}`,
        `L${x1},${y1 + hb}`,
        `C${mid},${y1 + hb} ${mid},${y0 + ha} ${x0},${y0 + ha}`,
        "Z",
      ].join(" "),
    };
  });

  return { nodes: [...placed.values()], paths, lastColumn };
}

export default function Sankey({ nodes = [], links = [], columns = [] }) {
  const [hover, setHover] = useState(null);
  const { nodes: placed, paths, lastColumn } = useMemo(
    () => layout(nodes, links),
    [nodes, links],
  );

  // Hovering anything lifts that node and everything directly attached to
  // it, and pushes the rest back. One read: "where did these 235 go?".
  const neighbours = useMemo(() => {
    if (!hover) return null;
    const near = new Set([hover]);
    links.forEach((link) => {
      if (link.source === hover) near.add(link.target);
      if (link.target === hover) near.add(link.source);
    });
    return near;
  }, [hover, links]);

  const dim = (...ids) => Boolean(neighbours) && !ids.some((id) => neighbours.has(id));

  if (!placed.length) {
    return <p className="analytics-empty">Sin llamadas en el periodo.</p>;
  }

  return (
    <div className="sankey">
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="sankey-svg" role="img">
        <title>Recorrido de las llamadas, del total a su desenlace</title>
        <g className="sankey-ribbons">
          {paths.map((path) => (
            <path
              key={path.id}
              d={path.d}
              className={`sankey-ribbon tone-${path.tone} ${
                dim(path.source, path.target) ? "is-dim" : ""
              }`}
              onMouseEnter={() => setHover(path.target)}
              onMouseLeave={() => setHover(null)}
            >
              <title>{`${path.value} llamadas`}</title>
            </path>
          ))}
        </g>
        <g className="sankey-nodes">
          {placed.map((node) => (
            <g
              key={node.id}
              onMouseEnter={() => setHover(node.id)}
              onMouseLeave={() => setHover(null)}
              className={dim(node.id) ? "is-dim" : ""}
            >
              <rect
                x={node.x}
                y={node.y}
                width={NODE_W}
                height={node.h}
                rx="3"
                className={`sankey-node tone-${node.tone}`}
              />
              <text
                x={node.x + NODE_W + LABEL_GAP}
                y={node.y + node.h / 2}
                className="sankey-label"
                dominantBaseline="middle"
              >
                <tspan className="sankey-label-value">{node.value}</tspan>
                <tspan dx="7">{node.label}</tspan>
              </text>
            </g>
          ))}
        </g>
      </svg>
      {columns.length > 0 && (
        <div className="sankey-legend">
          {columns.map((label, index) => (
            <span
              key={label}
              className="sankey-legend-item"
              style={{
                left: `${((index / lastColumn) * (WIDTH - NODE_W - 300) * 100) / WIDTH}%`,
              }}
            >
              {label}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
