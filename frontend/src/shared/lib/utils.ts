import type { RuleGroupType } from 'react-querybuilder';

type QueryNode = {
  field?: string;
  operator?: string;
  value?: unknown;
  valueSource?: string;
  rules?: QueryNode[];
  combinator?: string;
  not?: boolean;
};

export function queryToDsl(group: RuleGroupType): Record<string, unknown> {
  const walk = (node: QueryNode): Record<string, unknown> => {
    if (node.rules) {
      const children = node.rules.map(walk);
      if (node.not) return { not: children[0] ?? {} };
      return node.combinator === "or" ? { any: children } : { all: children };
    }
    const opMap: Record<string, string> = {
      "=": "eq",
      "!=": "ne",
      ">": "gt",
      ">=": "gte",
      "<": "lt",
      "<=": "lte",
      contains: "contains",
      in: "in",
    };
    const field = node.field ?? "";
    const fieldEntity = field.split(".", 1)[0];
    const counterpartEntity = fieldEntity === "order" ? "executor" : "order";
    const value =
      node.valueSource === "field"
        ? { field: String(node.value ?? `${counterpartEntity}.`) }
        : node.value;
    return {
      field,
      op: opMap[node.operator ?? "="] ?? node.operator ?? "eq",
      value,
    };
  };
  return walk(group as unknown as QueryNode);
}
