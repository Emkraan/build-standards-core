/* The node graph: a themed wrapper around React Flow (@xyflow/react, an optional peer dependency),
   for node-link, flow and dependency diagrams. Every node is a React component, so a node is styled
   with the same tokens and parts as the rest of the app.

   graph.css (import once: `kit-core/graph.css`) loads the React Flow base sheet into the kit-vendor
   layer and maps its --xy-* variables onto the kit tokens, so the canvas, edges, controls and minimap
   follow the theme with no theme branch. React Flow also takes a colour mode for the few colours it
   keeps to itself; it follows the kit theme by default.

   Two modes, fixed for the life of a mount: controlled (pass `nodes`, `edges` and the change
   handlers, for an editor) and uncontrolled (pass `defaultNodes` and `defaultEdges`; the graph owns
   the interaction state, for a read-only or lightly interactive diagram). */

import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  useEdgesState,
  useNodesState,
} from '@xyflow/react';
import type { ColorMode, Edge, EdgeMarker, Node, NodeProps, NodeTypes, ReactFlowProps } from '@xyflow/react';
import { useMemo } from 'react';
import type { CSSProperties, ReactNode } from 'react';
import { cx } from '../lib/env';
import type { MarkHue } from '../lib/hues';
import { useColorScheme } from '../lib/media';

export type { Connection, Edge, EdgeChange, Node, NodeChange, NodeProps, NodeTypes } from '@xyflow/react';

/** What the built-in `card` node shows. */
export interface GraphNodeData extends Record<string, unknown> {
  /** The node title. Wraps rather than truncates, so the card grows in height. */
  label: string;
  /** A short caption above the title: the kind of thing the node is. */
  kind?: string;
  /** One monospace line under the title: a host name, an address, an id. */
  detail?: string;
  /** Small chips under the title: ports, roles, versions. The first four show. */
  meta?: readonly string[];
  /** A 16px glyph in the icon tile. Decorative. */
  icon?: ReactNode;
  /** A categorical hue that tints the card, its border and its icon tile. */
  hue?: MarkHue;
  /** A dashed border: a planned, external or optional node. */
  dashed?: boolean;
}

/** A node drawn by the built-in `card` node type. */
export type GraphCardNode = Node<GraphNodeData, 'card'>;

export interface GraphNodeCardProps extends GraphNodeData {
  /** Draws the selection ring. Pass the `selected` React Flow gives a node component. */
  selected?: boolean;
  /** Renders the four connection handles (target on top and left, source on bottom and right).
      Default true. Handles need a React Flow node context, so turn them off outside a graph. */
  handles?: boolean;
}

/** The node card on its own, for a custom node type that wants the kit card with its own content
    around it. The built-in `card` type renders exactly this. */
export function GraphNodeCard({ label, kind, detail, meta, icon, hue, dashed, selected, handles = true }: GraphNodeCardProps) {
  const chips = meta?.slice(0, 4) ?? [];
  return (
    <div
      className={cx('flow-node', hue && `hue-${hue}`)}
      data-hue={hue}
      data-dashed={dashed ? '' : undefined}
      data-selected={selected ? '' : undefined}
    >
      {handles ? (
        <>
          <Handle type="target" position={Position.Top} />
          <Handle type="source" position={Position.Bottom} />
          <Handle type="target" position={Position.Left} id="left" />
          <Handle type="source" position={Position.Right} id="right" />
        </>
      ) : null}
      <div className="flow-node-head">
        {icon ? (
          <span className="flow-node-icon" aria-hidden="true">
            {icon}
          </span>
        ) : null}
        <div className="flow-node-titles">
          {kind ? <span className="flow-node-kind">{kind}</span> : null}
          <span className="flow-node-label">{label}</span>
        </div>
      </div>
      {chips.length > 0 ? (
        <ul className="flow-node-meta">
          {chips.map((m) => (
            <li key={m}>{m}</li>
          ))}
        </ul>
      ) : null}
      {detail ? <span className="flow-node-detail">{detail}</span> : null}
    </div>
  );
}

function CardNode({ data, selected }: NodeProps<GraphCardNode>) {
  return <GraphNodeCard {...data} selected={selected} />;
}

/** The node types every Graph knows: `card` draws GraphNodeCard. Spread it into your own map when
    you build the map outside a Graph. */
export const graphNodeTypes = { card: CardNode } satisfies NodeTypes;

/** What graphEdge draws. */
export interface GraphEdgeSpec {
  id: string;
  source: string;
  target: string;
  /** The handle the edge leaves from (`right` for the side handle) and lands on (`left`). */
  sourceHandle?: string;
  targetHandle?: string;
  /** A short label on the edge midpoint. */
  label?: string;
  /** A categorical hue for the stroke and the arrow. Neutral when omitted. */
  hue?: MarkHue;
  /** Arrows at both ends. */
  twoWay?: boolean;
  /** A dashed stroke: a planned or optional link. */
  dashed?: boolean;
  /** The moving dash React Flow draws for live traffic. Still under reduced motion. */
  animated?: boolean;
}

/** Builds a React Flow edge in the kit style: a bezier with a closed arrow, a token stroke (the
    selected stroke stays the accent) and a token label chip. */
export function graphEdge(spec: GraphEdgeSpec): Edge {
  const colour = spec.hue ? `rgb(var(--hue-${spec.hue}))` : 'var(--border-strong)';
  const arrow: EdgeMarker = { type: MarkerType.ArrowClosed, color: colour };
  const style = { '--xy-edge-stroke': colour } as CSSProperties;
  if (spec.dashed) style.strokeDasharray = '5 4';
  const edge: Edge = {
    id: spec.id,
    source: spec.source,
    target: spec.target,
    type: 'default',
    animated: spec.animated ?? false,
    markerEnd: arrow,
    style,
  };
  if (spec.sourceHandle) edge.sourceHandle = spec.sourceHandle;
  if (spec.targetHandle) edge.targetHandle = spec.targetHandle;
  if (spec.twoWay) edge.markerStart = arrow;
  if (spec.label) {
    edge.label = spec.label;
    edge.labelBgPadding = [4, 2];
    edge.labelBgBorderRadius = 4;
  }
  return edge;
}

/** The colour the minimap paints a node: its card hue, else the neutral node fill. */
function minimapColour(node: Node): string {
  const hue = (node.data as Partial<GraphNodeData> | undefined)?.hue;
  return hue ? `rgb(var(--hue-${hue}))` : 'var(--surface-4)';
}

export interface GraphProps {
  /** The accessible name of the diagram. */
  label: string;
  /** Controlled nodes. Pass with `onNodesChange` for an editable graph. */
  nodes?: Node[];
  edges?: Edge[];
  onNodesChange?: ReactFlowProps['onNodesChange'];
  onEdgesChange?: ReactFlowProps['onEdgesChange'];
  /** Called when the user drags a new connection. Connecting is off without it. */
  onConnect?: ReactFlowProps['onConnect'];
  onNodeClick?: ReactFlowProps['onNodeClick'];
  onEdgeClick?: ReactFlowProps['onEdgeClick'];
  /** The uncontrolled seed: the graph owns its state when `nodes` is omitted. */
  defaultNodes?: Node[];
  defaultEdges?: Edge[];
  /** Custom node components keyed by node `type`, merged over the built-in `card`. Keep the object
      stable (module scope or memoised): React Flow remounts every node when it changes. */
  nodeTypes?: NodeTypes;
  /** No dragging, connecting or deleting. Selection and the viewport still work. */
  readOnly?: boolean;
  /** The colour mode React Flow uses for the colours it keeps. Default: the kit theme. */
  colorMode?: ColorMode;
  /** The zoom and fit controls. Default true. */
  controls?: boolean;
  /** The minimap. Default false. */
  minimap?: boolean;
  /** Fit the graph into view on mount. Default true. */
  fitView?: boolean;
  /** The canvas height. Default 420px. Pass '100%' to fill a parent that has a height. */
  height?: number | string;
  className?: string;
  style?: CSSProperties;
  /** Overlay content inside the canvas: a React Flow Panel holding a toolbar or a legend. */
  children?: ReactNode;
}

type ControlledProps = GraphProps & { nodes: Node[]; edges: Edge[] };

function ControlledGraph({
  label,
  nodes,
  edges,
  onNodesChange,
  onEdgesChange,
  onConnect,
  onNodeClick,
  onEdgeClick,
  nodeTypes,
  readOnly = false,
  colorMode,
  controls = true,
  minimap = false,
  fitView = true,
  height = 420,
  className,
  style,
  children,
}: ControlledProps) {
  const scheme = useColorScheme();
  const types = useMemo<NodeTypes>(() => ({ ...graphNodeTypes, ...nodeTypes }), [nodeTypes]);
  // exactOptionalPropertyTypes: React Flow rejects an explicit undefined handler, so pass only
  // the handlers the caller gave.
  const handlers: Partial<ReactFlowProps> = {};
  if (onNodesChange) handlers.onNodesChange = onNodesChange;
  if (onEdgesChange) handlers.onEdgesChange = onEdgesChange;
  if (onConnect && !readOnly) handlers.onConnect = onConnect;
  if (onNodeClick) handlers.onNodeClick = onNodeClick;
  if (onEdgeClick) handlers.onEdgeClick = onEdgeClick;
  return (
    <div role="group" aria-label={label} className={cx('kit-flow', className)} style={{ height, ...style }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        {...handlers}
        nodeTypes={types}
        colorMode={colorMode ?? scheme}
        fitView={fitView}
        fitViewOptions={{ padding: 0.15 }}
        minZoom={0.2}
        maxZoom={2}
        nodesDraggable={!readOnly}
        nodesConnectable={!readOnly && onConnect !== undefined}
        deleteKeyCode={readOnly ? null : ['Backspace', 'Delete']}
      >
        <Background variant={BackgroundVariant.Dots} gap={28} size={1} />
        {controls ? <Controls showInteractive={false} /> : null}
        {minimap ? <MiniMap pannable zoomable nodeColor={minimapColour} nodeStrokeWidth={0} /> : null}
        {children}
      </ReactFlow>
    </div>
  );
}

function UncontrolledGraph({ defaultNodes = [], defaultEdges = [], ...rest }: GraphProps) {
  const [nodes, , onNodesChange] = useNodesState(defaultNodes);
  const [edges, , onEdgesChange] = useEdgesState(defaultEdges);
  return <ControlledGraph {...rest} nodes={nodes} edges={edges} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} />;
}

/** The kit node graph. Controlled when `nodes` is passed, otherwise it owns its state, seeded from
    `defaultNodes` and `defaultEdges`. Nodes of type `card` draw the kit node card. */
export function Graph(props: GraphProps) {
  const { nodes, edges } = props;
  return nodes !== undefined ? <ControlledGraph {...props} nodes={nodes} edges={edges ?? []} /> : <UncontrolledGraph {...props} />;
}
