# ADR-0014: Dependency Graph Engine (NetworkX)

**Status**: Accepted  
**Date**: 2026-01-27  
**Author**: Shamim Rehman  
**Reviewers**: -

## Context

ScaleScore analyzes dependencies between organizational entities (teams, systems, vendors, facilities) to:

- Detect bottlenecks that could cascade through the organization
- Identify single points of failure
- Calculate impact scores based on dependency chains
- Visualize dependency relationships

Currently:
- NetworkX is listed as a dependency in pyproject.toml
- A custom `DependencyNode` dataclass exists in bottleneck_detector.py
- There's no formal decision on when to use NetworkX vs. custom structures

This creates ambiguity about:
- When to use NetworkX graph algorithms
- How to persist and serialize graphs
- Performance implications for large organizations
- Memory management for complex dependency chains

## Decision Drivers

- **Scale**: Must handle 1000+ entities with complex relationships
- **Performance**: Graph operations must be fast (<100ms for analysis)
- **Flexibility**: Support various graph algorithms (cycles, paths, centrality)
- **Simplicity**: Don't over-engineer for current needs
- **Persistence**: Graphs must be serializable for storage

## Considered Options

### Option 1: NetworkX for All Graph Operations

Use NetworkX as the primary graph engine for all dependency operations.

**Pros:**
- Comprehensive algorithm library
- Well-documented and maintained
- Excellent for analysis (centrality, paths, cycles)
- Visualization integration (matplotlib, graphviz)
- Active community

**Cons:**
- Memory overhead for simple cases
- Serialization requires custom handling
- Learning curve for team
- May be overkill for simple dependency tracking

### Option 2: Custom Graph Implementation

Build custom graph data structures tailored to our needs.

**Pros:**
- Optimized for specific use cases
- Full control over serialization
- Minimal dependencies
- Lighter memory footprint

**Cons:**
- Reinventing the wheel
- Maintenance burden
- Missing algorithm implementations
- Testing burden

### Option 3: Hybrid Approach

Use simple dataclasses for data model, NetworkX for analysis.

**Pros:**
- Best of both worlds
- Clean data models
- Powerful analysis when needed
- Flexibility to optimize hot paths

**Cons:**
- Must maintain conversion layer
- Two representations to sync
- Potential consistency issues

### Option 4: Graph Database (Neo4j)

Store and query graphs in a graph database.

**Pros:**
- Native graph storage and queries
- Cypher query language
- Built for large graphs
- ACID transactions

**Cons:**
- Infrastructure complexity
- Overkill for current scale
- Additional dependency
- Learning curve for Cypher

## Decision

**Use Option 3: Hybrid Approach with clear usage guidelines.**

We will:
1. **Pydantic models** for data representation and API serialization
2. **NetworkX graphs** for analysis operations (bottleneck detection, impact analysis)
3. **Clear conversion utilities** between representations
4. **Lazy graph construction** (build only when needed for analysis)
5. **No graph persistence** (reconstruct from entity relationships)

Rationale:
- Pydantic models provide clean API contracts and serialization
- NetworkX provides powerful algorithms without reimplementing
- Lazy construction avoids memory overhead for simple operations
- No graph persistence simplifies storage (derive from relationships)

## Consequences

### Positive
- Clean separation between data model and analysis
- Access to full NetworkX algorithm library
- Efficient API serialization via Pydantic
- No graph storage complexity

### Negative
- Conversion overhead when building graphs
- Must keep conversion utilities in sync with models
- Two mental models for developers

### Neutral
- Graph construction on-demand (trade memory for CPU)
- NetworkX is a required dependency

## Implementation Notes

### Data Models (Pydantic)

```python
# src/scalescore/models/core.py
from pydantic import BaseModel, Field


class Dependency(BaseModel):
    """Represents a dependency between entities."""
    source_id: str
    target_id: str
    dependency_type: str  # "requires", "uses", "managed_by", etc.
    criticality: str = "medium"  # low, medium, high, critical
    metadata: dict[str, Any] = Field(default_factory=dict)


class DependencyInfo(BaseModel):
    """Dependency information attached to an entity."""
    depends_on: list[str] = Field(default_factory=list)
    depended_by: list[str] = Field(default_factory=list)


class System(BaseModel):
    """System entity with dependencies."""
    id: str
    name: str
    owner_team_id: str | None = None
    dependencies: DependencyInfo = Field(default_factory=DependencyInfo)
    
    # Direct dependency references for convenience
    upstream_systems: list[str] = Field(default_factory=list)
    downstream_systems: list[str] = Field(default_factory=list)
```

### Graph Builder

```python
# src/scalescore/core/graph.py
from typing import Any, Iterator
import networkx as nx

from scalescore.models.core import Organization, Team, System, Vendor, Facility


class DependencyGraphBuilder:
    """Builds NetworkX graphs from entity relationships."""
    
    def __init__(self):
        self._graph: nx.DiGraph | None = None
    
    def build_from_entities(
        self,
        organizations: list[Organization],
        teams: list[Team],
        systems: list[System],
        vendors: list[Vendor],
        facilities: list[Facility],
    ) -> nx.DiGraph:
        """
        Build a directed graph from all entity relationships.
        
        Nodes are entities, edges are dependencies.
        """
        g = nx.DiGraph()
        
        # Add all entities as nodes with type attribute
        for org in organizations:
            g.add_node(org.id, type="organization", entity=org)
        
        for team in teams:
            g.add_node(team.id, type="team", entity=team)
            # Team belongs to organization
            if team.organization_id:
                g.add_edge(team.id, team.organization_id, relation="belongs_to")
        
        for system in systems:
            g.add_node(system.id, type="system", entity=system)
            # System owned by team
            if system.owner_team_id:
                g.add_edge(system.id, system.owner_team_id, relation="owned_by")
            # System dependencies
            for dep_id in system.upstream_systems:
                g.add_edge(system.id, dep_id, relation="depends_on")
        
        for vendor in vendors:
            g.add_node(vendor.id, type="vendor", entity=vendor)
        
        for facility in facilities:
            g.add_node(facility.id, type="facility", entity=facility)
        
        self._graph = g
        return g
    
    @property
    def graph(self) -> nx.DiGraph:
        """Get the current graph, raising if not built."""
        if self._graph is None:
            raise ValueError("Graph not built. Call build_from_entities first.")
        return self._graph


class GraphAnalyzer:
    """Analyzes dependency graphs for bottlenecks and risks."""
    
    def __init__(self, graph: nx.DiGraph):
        self.graph = graph
    
    def find_critical_paths(
        self,
        source: str,
        target: str,
    ) -> list[list[str]]:
        """Find all paths between two nodes."""
        try:
            return list(nx.all_simple_paths(self.graph, source, target))
        except nx.NetworkXNoPath:
            return []
    
    def find_bottlenecks(
        self,
        threshold: float = 0.5,
    ) -> list[tuple[str, float]]:
        """
        Find nodes that are bottlenecks based on betweenness centrality.
        
        Betweenness centrality measures how often a node appears on
        shortest paths between other nodes.
        """
        centrality = nx.betweenness_centrality(self.graph)
        
        bottlenecks = [
            (node, score)
            for node, score in centrality.items()
            if score >= threshold
        ]
        
        return sorted(bottlenecks, key=lambda x: x[1], reverse=True)
    
    def find_single_points_of_failure(self) -> list[str]:
        """
        Find nodes whose removal would disconnect the graph.
        
        These are articulation points in the underlying undirected graph.
        """
        # Convert to undirected for articulation point analysis
        undirected = self.graph.to_undirected()
        
        if not nx.is_connected(undirected):
            # Graph is already disconnected, analyze components
            components = list(nx.connected_components(undirected))
            if len(components) > 1:
                # Return nodes that bridge components in directed graph
                return self._find_bridge_nodes()
        
        # Find articulation points
        return list(nx.articulation_points(undirected))
    
    def _find_bridge_nodes(self) -> list[str]:
        """Find nodes that connect otherwise disconnected components."""
        bridges = []
        for node in self.graph.nodes():
            # Check if removing this node increases component count
            temp_graph = self.graph.to_undirected()
            temp_graph.remove_node(node)
            
            original_components = nx.number_connected_components(
                self.graph.to_undirected()
            )
            new_components = nx.number_connected_components(temp_graph)
            
            if new_components > original_components:
                bridges.append(node)
        
        return bridges
    
    def calculate_impact_score(self, node: str) -> float:
        """
        Calculate impact score for a node based on its dependencies.
        
        Higher score = more entities depend on this node.
        """
        try:
            # Count all nodes that can reach this node
            ancestors = nx.ancestors(self.graph, node)
            # Count all nodes this node can reach
            descendants = nx.descendants(self.graph, node)
            
            total_nodes = len(self.graph.nodes())
            if total_nodes <= 1:
                return 0.0
            
            # Impact is proportion of graph affected
            affected = len(ancestors) + len(descendants)
            return affected / (total_nodes - 1)
            
        except nx.NetworkXError:
            return 0.0
    
    def detect_cycles(self) -> list[list[str]]:
        """Detect circular dependencies."""
        try:
            cycles = list(nx.simple_cycles(self.graph))
            return cycles
        except nx.NetworkXNoCycle:
            return []
    
    def get_dependency_chain(
        self,
        node: str,
        direction: str = "upstream",
    ) -> list[str]:
        """
        Get all dependencies in a direction.
        
        Args:
            node: Starting node
            direction: "upstream" (what this depends on) or 
                      "downstream" (what depends on this)
        """
        if direction == "upstream":
            return list(nx.descendants(self.graph, node))
        else:
            return list(nx.ancestors(self.graph, node))
```

### Usage in Bottleneck Detector

```python
# src/scalescore/core/bottleneck_detector.py
from scalescore.core.graph import DependencyGraphBuilder, GraphAnalyzer
from scalescore.models.scaling import Bottleneck, BottleneckType


class BottleneckDetector:
    """Detects bottlenecks in organizational structure."""
    
    def detect_bottlenecks(
        self,
        organizations: list[Organization],
        teams: list[Team],
        systems: list[System],
        vendors: list[Vendor],
        facilities: list[Facility],
    ) -> list[Bottleneck]:
        """Analyze entities and detect bottlenecks."""
        
        # Build graph lazily only when needed
        builder = DependencyGraphBuilder()
        graph = builder.build_from_entities(
            organizations=organizations,
            teams=teams,
            systems=systems,
            vendors=vendors,
            facilities=facilities,
        )
        
        analyzer = GraphAnalyzer(graph)
        bottlenecks = []
        
        # Find high-centrality nodes
        central_nodes = analyzer.find_bottlenecks(threshold=0.3)
        for node_id, centrality in central_nodes:
            node_data = graph.nodes[node_id]
            bottlenecks.append(
                Bottleneck(
                    entity_id=node_id,
                    entity_type=node_data["type"],
                    bottleneck_type=BottleneckType.DEPENDENCY_CONCENTRATION,
                    severity=self._centrality_to_severity(centrality),
                    impact_score=analyzer.calculate_impact_score(node_id),
                    description=f"High dependency concentration ({centrality:.2%})",
                )
            )
        
        # Find single points of failure
        spofs = analyzer.find_single_points_of_failure()
        for node_id in spofs:
            if node_id not in [b.entity_id for b in bottlenecks]:
                node_data = graph.nodes[node_id]
                bottlenecks.append(
                    Bottleneck(
                        entity_id=node_id,
                        entity_type=node_data["type"],
                        bottleneck_type=BottleneckType.SINGLE_POINT_OF_FAILURE,
                        severity="critical",
                        impact_score=analyzer.calculate_impact_score(node_id),
                        description="Single point of failure in dependency chain",
                    )
                )
        
        # Detect circular dependencies
        cycles = analyzer.detect_cycles()
        for cycle in cycles:
            bottlenecks.append(
                Bottleneck(
                    entity_id=cycle[0],  # First node in cycle
                    entity_type=graph.nodes[cycle[0]]["type"],
                    bottleneck_type=BottleneckType.CIRCULAR_DEPENDENCY,
                    severity="high",
                    impact_score=len(cycle) / len(graph.nodes()),
                    description=f"Circular dependency: {' -> '.join(cycle)}",
                    affected_entities=cycle,
                )
            )
        
        return bottlenecks
    
    def _centrality_to_severity(self, centrality: float) -> str:
        """Convert centrality score to severity level."""
        if centrality >= 0.7:
            return "critical"
        elif centrality >= 0.5:
            return "high"
        elif centrality >= 0.3:
            return "medium"
        return "low"
```

### Graph Visualization (Optional)

```python
# src/scalescore/core/graph_viz.py
from typing import Any
import networkx as nx


def graph_to_mermaid(graph: nx.DiGraph) -> str:
    """Convert graph to Mermaid diagram syntax."""
    lines = ["graph TD"]
    
    # Add nodes with labels
    for node, data in graph.nodes(data=True):
        entity_type = data.get("type", "unknown")
        label = f"{node}[{entity_type}: {node}]"
        lines.append(f"    {label}")
    
    # Add edges
    for source, target, data in graph.edges(data=True):
        relation = data.get("relation", "")
        if relation:
            lines.append(f"    {source} -->|{relation}| {target}")
        else:
            lines.append(f"    {source} --> {target}")
    
    return "\n".join(lines)


def graph_to_d3_json(graph: nx.DiGraph) -> dict[str, Any]:
    """Convert graph to D3.js compatible JSON."""
    nodes = [
        {
            "id": node,
            "type": data.get("type", "unknown"),
            **{k: v for k, v in data.items() if k != "entity"},
        }
        for node, data in graph.nodes(data=True)
    ]
    
    links = [
        {
            "source": source,
            "target": target,
            "relation": data.get("relation", ""),
        }
        for source, target, data in graph.edges(data=True)
    ]
    
    return {"nodes": nodes, "links": links}
```

### When to Use Each Approach

| Use Case | Approach |
|----------|----------|
| API request/response | Pydantic models |
| Database storage | Pydantic → dict → JSON |
| Simple dependency list | Pydantic `depends_on` list |
| Bottleneck detection | Build NetworkX graph |
| Path analysis | NetworkX algorithms |
| Cycle detection | NetworkX algorithms |
| Visualization | NetworkX → export format |

### Performance Considerations

```python
# For large graphs (1000+ nodes), consider:

# 1. Build graph once per assessment, reuse for multiple analyses
graph = builder.build_from_entities(...)
analyzer = GraphAnalyzer(graph)

# Do multiple analyses without rebuilding
bottlenecks = analyzer.find_bottlenecks()
spofs = analyzer.find_single_points_of_failure()
cycles = analyzer.detect_cycles()

# 2. Use approximate algorithms for very large graphs
# NetworkX supports approximate betweenness for large graphs
centrality = nx.betweenness_centrality(
    graph,
    k=100,  # Sample 100 nodes for approximation
)

# 3. Cache analysis results
from functools import lru_cache

@lru_cache(maxsize=100)
def get_impact_score(graph_hash: str, node: str) -> float:
    # Cache impact scores per graph version
    pass
```

## Related Decisions

- ADR-0001: Pydantic v2 for Models (data representation)
- ADR-0003: Constraint-Based Scoring (bottleneck impact on scores)
- ADR-0012: Background Job Processing (async graph analysis)

## Notes

- Consider adding graph metrics to observability (node count, edge count, analysis time)
- For very large organizations, consider graph partitioning
- NetworkX 3.0+ has improved performance over earlier versions
- May need to revisit if graph size exceeds 10,000 nodes
