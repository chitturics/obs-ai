# stats

## Description

The `stats` command calculates aggregate statistics over the results set, similar to SQL aggregation. Use the stats command to calculate statistics on fields in search results.

## Syntax

```
stats <stats-function>... [as <field>] [by <field-list>]
```

## Required arguments

**stats-function**: Statistical function to apply. Supported functions include:
- `count` - Returns the number of events
- `avg(X)` - Returns the average of field X
- `sum(X)` - Returns the sum of field X
- `min(X)` - Returns the minimum value of field X
- `max(X)` - Returns the maximum value of field X
- `dc(X)` - Returns the distinct count of field X
- `values(X)` - Returns all distinct values of field X
- `list(X)` - Returns all values of field X (including duplicates)

## Optional arguments

**by-clause**: Group results by the specified fields.

## Examples

### Example 1: Count events by sourcetype
```spl
index=main | stats count by sourcetype
```

### Example 2: Average response time by host
```spl
index=web | stats avg(response_time) as avg_rt by host
```

### Example 3: Multiple aggregations
```spl
index=security | stats count, dc(src_ip) as unique_sources, values(action) as actions by user
```
