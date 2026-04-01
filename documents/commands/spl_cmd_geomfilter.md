---
 command: geomfilter
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/geomfilter
 title: geomfilter
 download_date: 2026-02-03 09:08:46
---

 # geomfilter

Use the geomfilter command to specify points of a bounding box for clipping choropleth maps.

For more information about choropleth maps, see "Mapping data" in the Dashboards and Visualizations Manual.

geomfilter [min_x=<float>] [min_y=<float>] [max_x=<float>] [max_y=<float>]

#### Optional arguments

The geomfilter command accepts two points that specify a bounding box for clipping choropleth maps. Points that fall outside of the bounding box will be filtered out.

Example 1: This example uses the default bounding box, which will clip the entire map.

...| geomfilter min_x=-90 min_y=-90 max_x=90 max_y=90
 