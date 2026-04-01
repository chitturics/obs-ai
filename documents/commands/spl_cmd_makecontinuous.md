---
 command: makecontinuous
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/makecontinuous
 title: makecontinuous
 download_date: 2026-02-03 09:10:54
---

 # makecontinuous

# makecontinuous

## Description

Makes a field on the x-axis numerically continuous by adding empty buckets for periods where there is no data and quantifying the periods where there is data. This x-axis field can then be invoked by the chart and timechart commands.

## Syntax

The required syntax is in bold.

makecontinuous

[<bin-options>...]

### Required arguments

<bins-options>

Datatype: bins | span | start-end

Description: Discretization options. See "Bins options" for details.

### Optional arguments

Datatype: <field>

Description: Specify a field name.

### Bins options

Syntax: bins=<int>

Description: Sets the maximum number of bins to discretize into.

Syntax: <log-span> | <span-length>

Description: Sets the size of each bin, using a span length based on time or log-based span.

<start-end>

Syntax: end=<num> | start=<num>

Description: Sets the minimum and maximum extents for numerical bins. Data outside of the [start, end] range is discarded.

### Span options

Syntax: [<num>]log[<num>]

Description: Sets to log-based span. The first number is a coefficient. The second number is the base. If the first number is supplied, it must be a real number >= 1.0 and < base. Base, if supplied, must be real number > 1.0, meaning it must be strictly greater than 1.

span-length

Syntax: <span>[<timescale>]

Description: A span length based on time.

Syntax: <int>

Description: The span of each bin. If using a timescale, this is used as a time range. If not, this is an absolute bin "length."

<timescale>

Syntax: <sec> | <min> | <hr> | <day> | <month> | <subseconds>

Description: Time scale units.

## Usage

The makecontinuous command is a transforming command. See Command types.

## Examples

### Example 1:

Make the _time field continuous with a span of 10 minutes.

## See also

chart, timechart
 