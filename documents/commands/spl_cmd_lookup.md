---
 command: lookup
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/lookup
 title: lookup
 download_date: 2026-02-03 09:10:46
---

 # lookup

Use the lookup command to invoke field value lookups.

For information about the types of lookups you can define, see About lookups in the Knowledge Manager Manual.

The lookup command supports IPv4 and IPv6 addresses and subnets that use CIDR notation.

The required syntax is in bold.

Note: The lookup command can accept multiple lookup and event fields and destfields. For example:

#### Required arguments

#### Optional arguments

The lookup command is a distributable streaming command when local=false, which is the default setting. 
See Command types.

When using the lookup command, if an OUTPUT or OUTPUTNEW clause is not specified, all of the fields in the lookup table that are not the match fields are used as output fields. If the OUTPUT clause is specified, the output lookup fields overwrite existing fields. If the OUTPUTNEW clause is specified, the lookup is not performed for events in which the output fields already exist.

#### Avoid lookup reference cycles

When you set up the OUTPUT or OUTPUTNEW clause for your lookup, avoid accidentally creating lookup reference cycles, where you intentionally or accidentally reuse the same field names among the match fields and the output fields of a lookup search.

For example, if you run a lookup search where type is both the match field and the output field, you are creating a lookup reference cycle. You can accidentally create a lookup reference cycle when you fail to specify an OUTPUT or OUTPUTNEW clause for lookup.

For more information about lookup reference cycles see Define an automatic lookup in Splunk Web in the Knowledge Manager Manual.

#### Optimizing your lookup search

If you are using the lookup command in the same pipeline as a transforming command, and it is possible to retain the field you will lookup on after the transforming command, do the lookup after the transforming command. For example, run:

The lookup in the first search is faster because it only needs to match the results of the stats command and not all the Web access events.

If you are running federated searches over standard mode Splunk platform federated providers, and you want to use lookup to enrich the results of a federated search, consider whether you want the search to be processed on your local federated search head, or on the remote search heads of the federated providers you invoke in your search.

For an overview of federated search for Splunk, see About Federated Search for Splunk in Federated Search.

#### If you want to process your lookup on the remote search heads of your federated providers

Standard mode federated searches that involve lookups complete faster on average when the lookup portion of the search is processed on the remote search heads of the federated providers invoked in the search. However, the lookup portions of federated searches run on the remote search heads only when one or more of the following statements are true:

- No other commands precede the lookup command.
- One or more distributable streaming commands precedes the lookup command. See Types of commands in the Search Manual.
- A search or from command precedes the lookup command.

In all other cases the search is processed on the federated search head of your local deployment.

If you set up your federated search so that the remote search heads of your federated providers process a lookup, the following conditions must be met for the search to return results.

- The lookup definition and lookup table expected by the lookup command must exist on the remote search heads.
- The service accounts on those federated providers must have access permissions for the lookup definition and lookup table.

#### If you want to process your lookup on the federated search head of your local Splunk platform deployment

If you are using standard mode federated search, and you want to process the lookup on your local federated search head, apply local=true to the search. When you apply local=true to a federated lookup search, the following things happen:

- The lookup is processed on your local federated search head, using a lookup definition and lookup table that are located on that search head.
- All commands following the lookup are also processed on the local federated search head.
- The portion of the search that precedes the lookup command is processed on the remote search head of the federated provider.

Note: When you set local=true for lookup in a federated search, it overrides the conditions that would cause the search to be processed on the remote search heads of the federated providers invoked in the search.

If you set up your federated search so that your local federated search head processes the lookup, the following conditions must be met for the search to return results.

- The lookup definition and lookup table expected by the lookup command must exist on the federated search head.
- The person running the search must have access permissions for the lookup definition and lookup table.

#### 1. Lookup users and return the corresponding group the user belongs to

Suppose you have a lookup table specified in a stanza named usertogroup in the transforms.conf file. This lookup table contains (at least) two fields, user and group. Your events contain a field called local_user. For each event, the following search checks to see if the value in the field local_user has a corresponding value in the user field in the lookup table. For any entries that match, the value of the group field in the lookup table is written to the field user_group in the event.

#### 1. Lookup price and vendor information and return the count for each product sold by a vendor

| This example uses the tutorialdata.zip file from the Search Tutorial. You can download this file and add it to your Splunk deployment. See upload the tutorial data. Additionally, this example uses the prices.csv and the vendors.csv files. To follow along with this example in your Splunk deployment, download these CSV files and complete the steps in the Use field lookups section of the Search Tutorial for both the prices.csv and the vendors.csv files. When you create the lookup definition for the vendors.csv file, name the lookup vendors_lookup. You can skip the step in the tutorial that makes the lookups automatic. |

This example calculates the count of each product sold by each vendor.

The prices.csv file contains the product names, price, and code. For example:

| productId | product_name | price | sale_price | Code |
| --- | --- | --- | --- | --- |
| DB-SG-G01 | Mediocre Kingdoms | 24.99 | 19.99 | A |
| DC-SG-G02 | Dream Crusher | 39.99 | 24.99 | B |
| FS-SG-G03 | Final Sequel | 24.99 | 16.99 | C |
| WC-SH-G04 | World of Cheese | 24.99 | 19.99 | D |

The vendors.csv file contains vendor information, such as vendor name, city, and ID. For example:

| Vendor | VendorCity | VendorID | VendorLatitude | VendorLongitude | Vendor StateProvince | Vendor Country | Weight |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Anchorage Gaming | Anchorage | 1001 | 61.17440033 | -149.9960022 | Alaska | United States | 3 |
| Games of Salt Lake | Salt Lake City | 1002 | 40.78839874 | -111.9779968 | Utah | United States | 3 |
| New Jack Games | New York | 1003 | 40.63980103 | -73.77890015 | New York | United States | 4 |
| Seals Gaming | San Francisco | 1004 | 37.61899948 | -122.375 | California | United States | 5 |

The search will query the vendor_sales.log file, which is part of the tutorialdata.zip file. The vendor_sales.log file contains the VendorID, Code, and AcctID fields. For example:

| Entries in the vendor_sales.log file |
| --- |
| [13/Mar/2018:18:24:02] VendorID=5036 Code=B AcctID=6024298300471575 |
| [13/Mar/2018:18:23:46] VendorID=7026 Code=C AcctID=8702194102896748 |
| [13/Mar/2018:18:23:31] VendorID=1043 Code=B AcctID=2063718909897951 |
| [13/Mar/2018:18:22:59] VendorID=1243 Code=F AcctID=8768831614147676 |

The following search calculates the count of each product sold by each vendor and uses the time range All time.

- The stats command calculates the count by Code and VendorID.
- The lookup command uses the prices_lookup to match the Code field in each event and return the product names.

The search results are displayed on displayed on the Statistics tab.

Use the table command to return only the fields that you need. In this example you want the product_name, VendorID, and count fields. Use the vendors_lookup file to output all the fields in the vendors.csv file that match the VendorID in each event.

The revised search results are displayed on the Statistics tab.

To expand the search to display the results on a map, see the geostats command.

#### 2. IPv6 CIDR match in Splunk Web

In this example, CSV lookups are used to determine whether a specified IPv6 address is in a CIDR subnet. You can follow along with the example by performing these steps in Splunk Web. See Define a CSV lookup in Splunk Web.

Prerequisites

- Your role must have the upload_lookup_files capability to upload lookup table files in Splunk Web. See Define roles with capabilities in Splunk Enterprise "Securing the Splunk Platform".
- A CSV lookup table file called ipv6test.csv that contains the following text.  ip,expected  2001:0db8:ffff:ffff:ffff:ffff:ffff:ff00/120,true The ip field in the lookup table contains the subnet value, not the IP address.

You have to define a CSV lookup before you can match an IP address to a subnet.

- Select Settings > Lookups to go to the Lookups manager page.
- Click Add new next to Lookup table files.
- Select a Destination app from the drop-down list.
- Click Choose File to look for the ipv6test.csv file to upload.
- Enter ipv6test.csv as the destination filename. This is the name the lookup table file will have on the Splunk server.
- Click Save.
- In the Lookup table list, click Permissions in the Sharing column of the ipv6test lookup you want to share.
- In the Permissions dialog box, under Object should appear in, select All apps to share globally. If you want the lookup to be specific to this app only, select This app only. 
                Note: Permissions for lookup table files must be at the same level or higher than those of the lookup definitions that use those files.
- Click Save.
- Select Settings > Lookups.
- Click Add new next to Lookup definitions.
- Select a Destination app from the drop-down list.
- Give your lookup definition a unique Name, like ipv6test.
- Select File-based as the lookup Type.
- Select ipv6test.csv as the Lookup file from the drop-down list.
- Select the Advanced options check box.
- Enter a Match type of CIDR(ip).
- Click Save.
- In the Lookup definitions list, click Permissions in the Sharing column of the ipv6test lookup definition you want to share.
- In the Permissions dialog box, under Object should appear in, select All apps to share globally. If you want the lookup to be specific to this app only, select This app only. Note: Permissions for lookup table files must be at the same level or higher than those of the lookup definitions that use those files.
- Click Save.

| time | expected | ip |
| --- | --- | --- |
| 2020-11-19 16:43:31 | true | 2001:0db8:ffff:ffff:ffff:ffff:ffff:ff99 |
 