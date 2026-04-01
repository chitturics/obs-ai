---
 command: contingency
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/contingency
 title: contingency, counttable, ctable
 download_date: 2026-02-03 09:03:41
---

 # contingency

In statistics, contingency tables are used to record and analyze the relationship between two or more (usually categorical) variables.  Many metrics of association or independence, such as the phi coefficient or the Cramer's V, can be calculated based on contingency tables.

You can use the contingency command to build a contingency table, which in this case is a co-occurrence matrix for the values of two fields in your data. Each cell in the matrix displays the count of events in which both of the cross-tabulated field values exist. This means that the first row and column of this table is made up of values of the two fields. Each cell in the table contains a number that represents the count of events that contain the two values of the field in that row and column combination.

If a relationship or pattern exists between the two fields, you can spot it easily just by analyzing the information in the table. For example, if the column values vary significantly between rows (or vice versa), there is a contingency between the two fields (they are not independent). If there is no contingency, then the two fields are independent.

contingency [<contingency-options>...] <field1> <field2>

#### Required arguments

#### Optional arguments

#### Contingency options

The contingency command is a transforming command. See Command types.

This command builds a contingency table for two fields. If you have fields with many values, you can restrict the number of rows and columns using the maxrows and maxcols arguments.

#### Totals

By default, the contingency table displays the row totals, column totals, and a grand total for the counts of events that are represented in the table. If you don't want the totals to appear in the results, include the usetotal=false argument with the contingency command.

#### Empty values

Values which are empty strings ("") will be represented in the results table as EMPTY_STR.

#### Limits

There is a limit on the value of  maxrows or maxcols, which means more than 1000 values for either field will not be used.

#### 1. Build a contingency table of recent data

| This search uses recent earthquake data downloaded from the USGS Earthquakes website. The data is a comma separated ASCII text file that contains magnitude (mag), coordinates (latitude, longitude), region (place), etc., for each earthquake recorded.
You can download a current CSV file from the USGS Earthquake Feeds and upload the file to your Splunk instance.  This example uses the All Earthquakes data from  the past 30 days. Use the time range All time when you run the searches. |

You want to build a contingency table to look at the relationship between the magnitudes and depths of recent earthquakes.  You start with a simple search.

source=all_month.csv | contingency mag depth | sort mag

There are quite a range of values for the Magnitude and Depth fields, which results in a very large table. The magnitude values appear in the first column. The depth values appear in the first row. The list is sorted by magnitude.

The results appear on the Statistics tab. The following table shows only a small portion of the table of results returned from the search.

| mag | 10 | 0 | 5 | 35 | 8 | 12 | 15 | 11.9 | 11.8 | 6.4 | 5.4 | 8.2 | 6.5 | 8.1 | 5.6 | 10.1 | 9 | 8.5 | 9.8 | 8.7 | 7.9 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| -0.81 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| -0.59 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| -0.56 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| -0.45 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| -0.43 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

As you can see, earthquakes can have negative magnitudes. Only where an earthquake occurred that matches the magnitude and depth will a count appear in the table.

To build a more usable contingency table, you should reformat the values for the magnitude and depth fields. Group the magnitudes and depths into ranges.

source=all_month.csv  
| eval Magnitude=case(mag<=1, "0.0 - 1.0", mag>1 AND mag<=2, "1.1 - 2.0", mag>2 
  AND mag<=3, "2.1 - 3.0", mag>3 AND mag<=4, "3.1 - 4.0", mag>4 
  AND mag<=5, "4.1 - 5.0", mag>5 AND mag<=6, "5.1 - 6.0", mag>6 
  AND mag<=7, "6.1 - 7.0", mag>7,"7.0+") 
| eval Depth=case(depth<=70, "Shallow", depth>70 AND depth<=300, "Mid", depth>300 
  AND depth<=700, "Deep") 
| contingency Magnitude Depth 
| sort Magnitude

This search uses the eval command with the case() function to redefine the values of Magnitude and Depth, bucketing them into a range of values. For example, the Depth values are redefined as "Shallow", "Mid", or "Deep". Use the sort command to sort the results by magnitude.  Otherwise the results are sorted by the row totals.

The results appear on the Statistics tab and look something like this:

| Magnitude | Shallow | Mid | Deep | TOTAL |
| --- | --- | --- | --- | --- |
| 0.0 - 1.0 | 3579 | 33 | 0 | 3612 |
| 1.1 - 2.0 | 3188 | 596 | 0 | 3784 |
| 2.1 - 3.0 | 1236 | 131 | 0 | 1367 |
| 3.1 - 4.0 | 320 | 63 | 1 | 384 |
| 4.1 - 5.0 | 400 | 157 | 43 | 600 |
| 5.1 - 6.0 | 63 | 12 | 3 | 78 |
| 6.1 - 7.0 | 2 | 2 | 1 | 5 |
| TOTAL | 8788 | 994 | 48 | 9830 |

There were a lot of quakes in this month. Do higher magnitude earthquakes have a greater depth than lower magnitude earthquakes? Not really. The table shows that the majority of the recent earthquakes in all of magnitude ranges were shallow. There are significantly fewer earthquakes in the mid-to-deep range. In this data set, the deep-focused quakes were all in the mid-range of magnitudes.

#### 2. Identify potential component issues in the Splunk deployment

Determine if there are any components that might be causing issues in your Splunk deployment.
Build a contingency table to see if there is a relationship between the values of log_level and component. 
Run the search using the time range All time and limit the number of columns returned.

index=_internal | contingency maxcols=5 log_level component

Your results should appear something like this:

```
component
```

```
maxcols
```

associate, correlate
 