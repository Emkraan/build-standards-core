/* The `graph` entry: the node graph on React Flow (@xyflow/react, an optional peer dependency).
   Import from here, not from the kit root, so an app that draws no graph never loads React Flow.
   Import graph.css once alongside kit.css. Panel, Handle, Position and the rest of React Flow come
   from @xyflow/react itself. */

export { Graph, GraphNodeCard, graphEdge, graphNodeTypes } from './Graph';
export type {
  Connection,
  Edge,
  EdgeChange,
  GraphCardNode,
  GraphEdgeSpec,
  GraphNodeCardProps,
  GraphNodeData,
  GraphProps,
  Node,
  NodeChange,
  NodeProps,
  NodeTypes,
} from './Graph';
