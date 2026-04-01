---
 command: geostats
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/geostats
 title: geostats
 download_date: 2026-02-03 09:08:51
---

 # geostats

Use the geostats command to generate statistics to display geographic data and summarize the data on maps.

The command generates statistics which are clustered into geographical bins to be rendered on a world map.
The events are clustered based on latitude and longitude fields in the events. Statistics are then evaluated on the generated clusters. The statistics can be grouped or split by fields using a BY clause.

For map rendering and zooming efficiency, the geostats command generates clustered statistics at a variety of zoom levels in one search, the visualization selecting among them. The quantity of zoom levels is controlled by the binspanlat, binspanlong, and maxzoomlevel options. The initial granularity is selected by the binspanlat and the binspanlong.  At each level of zoom, the number of bins is doubled in both dimensions for a total of 4 times as many bins for each zoom in.

The required syntax is in bold.

#### Required arguments

#### Optional arguments

#### Stats function options

To display the information on a map, you must run a reporting search with the geostats command.

If you are using a lookup command before the geostats command, see Optimizing your lookup search.

#### Supported functions

You can use a wide range of functions with the geostats command. For general information about using functions, see  Statistical and charting functions.

- For a list of statistical functions by category, see Function list by category
- For an alphabetical list of statistical functions, see Alphabetical list of functions

#### Memory and geostats search performance

A pair of limits.conf settings strike a balance between the performance of geostats searches and the amount of memory they use during the search process, in RAM and on disk. If your geostats searches are consistently slow to complete you can adjust these settings to improve their performance, but at the cost of increased search-time memory usage, which can lead to search failures.

For more information, see Memory and stats search performance in the Search Manual.

#### 1. Use the default settings and calculate the count

Cluster events by default latitude and longitude fields "lat" and "lon" respectively. Calculate the count of the events.

#### 2. Specify the latfield and longfield and calculate the average of a field

Compute the average rating for each gender after clustering/grouping the events by "eventlat" and "eventlong" values.

... | geostats latfield=eventlat longfield=eventlong avg(rating) by gender

#### 3. Count each product sold by a vendor and display the information on a map

| This example uses the sample data from the Search Tutorial. To try this example on your own Splunk instance, you must download the sample data and follow the instructions to get the tutorial data into Splunk. Use the time range All time when you run the search.  In addition, this example uses several lookup files that you must download (prices.csv.zip and vendors.csv.zip) and unzip the files. You must complete the steps in the Enabling field lookups section of the tutorial for both the prices.csv and the vendors.csv files. The steps in the tutorial are specific to the prices.csv file. For the vendors.csv file, use the name vendors_lookup for the lookup definition. Skip the step in the tutorial that makes the lookups automatic. |

This search uses the stats command to narrow down the number of events that the lookup and geostats commands need to process.

Use the following search to count each product sold by a vendor and display the information on a map.

sourcetype=vendor_sales | stats  count by Code VendorID | lookup prices_lookup Code OUTPUTNEW product_name | table product_name VendorID | lookup vendors_lookup VendorID | geostats latfield=VendorLatitude longfield=VendorLongitude count by product_name

- In this example, sourcetype=vendor_sales is associated with a log file that is included in the Search Tutorial sample data. This log file contains vendor information that looks like this:

- The vendors_lookup is used to output all the fields in vendors.csv file that match to the VentorID in the vendor_sales.log file. The fields in the vendors.csv file are : Vendor, VendorCity, VendorID, VendorLatitude, VendorLongitude, VendorStateProvince, and VendorCountry.
- The prices_lookup is used to match the Code field in each event to a product_name in the table.

This search produces a table displayed on the Statistics tab:

Click the Visualization tab. The results are plotted on a world map. There is a pie chart for each vendor in the results. The larger the pie chart, the larger the count value.

In this screen shot, the mouse pointer is over the pie chart for a region in the northeastern part of the United States. An popup information box displays the latitude and longitude for the vendor, as well as a count of each product that the vendor sold.

You can zoom in to see more details on the map.
 