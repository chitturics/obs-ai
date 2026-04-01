---
 command: iplocation
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/iplocation
 title: iplocation
 download_date: 2026-02-03 09:09:50
---

 # iplocation

The iplocation command extracts location information from IP addresses by using 3rd-party databases. This command supports IPv4 and IPv6 addresses and subnets that use CIDR notation.

The IP address that you specify in the ip-address-fieldname argument, is looked up in a database. Fields from that database that contain location information are added to each event. The setting of the allfields argument determines which fields are added to the events.

Because all the information might not be available for each IP address, an event can have empty field values.

For IP addresses which do not have a location, such as internal addresses, no fields are added.

The required syntax is in bold.

#### Required arguments

#### Optional arguments

The iplocation command is a distributable streaming command. See Command types.

The Splunk software ships with a copy of the dbip-city-lite.mmdb IP geolocation database file. This file is located in the $SPLUNK_HOME/share/ directory.

#### Updating the IP geolocation database file

Through Splunk Web, you can update the .mmdb file that ships with the Splunk software. The file you update it with can be a copy of one of the following two files. Only those two files are supported. To use these two files, you must have a license for the GeoIP2 City database.

| File name | Description |
| --- | --- |
| GeoLite2-City.mmdb | This is a free IP geolocation database that is updated on its download page on a weekly basis. |
| GeoIP2-City.mmdb | This is a paid version of the GeoLite2-City IP geolocation database that is more accurate than the free version. |

Note: Replacing your mmdb file with one of these two files reintroduces the Timezone field that is absent in the default .mmdb file, but does not reintroduce the MetroCode field.

#### Prerequisites

You must have a role with the upload_mmdb_files capability.

#### Steps

- Go online and find a download page for the binary .tar.gz versions of the GeoLite2-City or the GeoIP2-City database files.
- Download the binary .tar.gz version of the file (GeoLite2-City or GeoIP2-City) that is most appropriate for your needs.
- Expand the binary .tar.gz version of the file.The .tar.gz file expands into a folder which contains the GeoLite2-City.mmdb file, or the GeoIP2-City.mmdb file, depending on the download you selected.
- In Splunk Web, go to Settings > Lookups > GeoIP lookups file.
- On the GeoIP lookups file page, click Choose file. Select the .mmdb file.
- Click Save.

The page displays a success message when the upload completes.

An .mmdb file that you upload through this method is treated as a lookup table by the Splunk software. This means it is picked up by knowledge bundle replication in distributed search environments, but that also means it can increase the size of knowledge bundles. See Knowledge bundle replication overview in the Distributed Search manual.

Note: If you upload your own .mmdb file in Splunk Web and later decide you want to revert back to the .mmdb file that was shipped with the Splunk software, go to Settings > Lookups > GeoIP lookups file and delete your uploaded file.

#### Impact of upgrading Splunk software

When you upgrade your Splunk platform, the .mmdb file in the $SPLUNK_HOME/share/ directory is replaced by the version of the file that ships with the Splunk software. You can avoid this by storing the .mmdb file in a different file path.

#### Storing the .mmdb file in a different file path

To store the GeoLite2-City.mmdb or GeoIP2-City.mmdb file in a different file path you must update the path directly in the limits.conf file. This is not possible in Splunk Cloud Platform, only Splunk Enterprise.

Note: The Splunk Web .mmdb file upload feature takes precedence over manual updates to the .mmdb file path in limits.conf.

#### Prerequisites

- Only users with file system access, such as system administrators, can specify a different file path to the .mmdb file in the limits.conf file.
- Review the steps in How to edit a configuration file in the Admin Manual.
- You can have configuration files with the same name in your default, local, and app directories. Read Where you can place (or find) your modified configuration files in the Admin Manual.

Note: Never change or copy the configuration files in the default directory. The files in the default directory must remain intact and in their original location. Make the changes in the local directory.

#### Steps

- Open the local limits.conf file for the Search app. For example, $SPLUNK_HOME/etc/apps/search/local.
- Add the [iplocation] stanza.
- Add the db_path setting and specify the absolute path to the .mmdb file. The db_path setting does not support standard Splunk environment variables such as $SPLUNK_HOME.
For example: db_path = /Applications/Splunk/mmdb/GeoLite2-City.mmdb specifies a new directory called mmdb.
- Ensure a copy of the .mmdb file is stored in the ../Applications/Splunk/mmdb/ directory.
- Because you are editing the path to the .mmdb file, you should restart the Splunk server.

#### Storing the .mmdb file with a different name

Alternatively, you can add the updated .mmdb to the $SPLUNK_HOME/share/ directory using a different name and then specify that name in the db_path setting. For example: db_path = /Applications/Splunk/share/GeoLite2-City_paid.mmdb.

#### The .mmdb file and distributed deployments

The iplocation command is a distributable streaming command, which means that it can be processed on the indexers. The $SPLUNK_HOME/share/ directory is not part of the knowledge bundle. If you update the .mmdb file in the $SPLUNK_HOME/share/ directory, the updated file is not automatically sent to the indexers in a distributed deployment. To add the .mmdb file to the indexers, use the tools that you typically use to push files to the indexers.

#### 1. Add location information to web access events

| This example uses the sample data from the Search Tutorial but should work with any format of Apache web access log. To try this example on your own Splunk instance, you must download the sample data and follow the instructions to get the tutorial data into Splunk. Use the time range All time when you run the search. |

Add location information to web access events. By default, the iplocation command adds the City, Country, lat, lon, and Region fields to the results.

#### 2. Search for client errors and return the first 20 results

| This example uses the sample data from the Search Tutorial but should work with any format of Apache web access log. To try this example on your own Splunk instance, you must download the sample data and follow the instructions to get the tutorial data into Splunk. Use the time range All time when you run the search. |

Search for client errors in web access events, returning only the first 20 results. Add location information and return a table with the IP address, City, and Country for each client error.

The results appear on the Statistics tab and look something like this:

| clientip | status | City | Country |
| --- | --- | --- | --- |
| 182.236.164.11 | 408 | Zhengzhou | China |
| 198.35.1.75 | 500 | Princeton | United States |
| 198.35.1.75 | 404 | Princeton | United States |
| 198.35.1.75 | 406 | Princeton | United States |
| 198.35.1.75 | 500 | Princeton | United States |
| 221.204.246.72 | 503 | Taiyuan | China |
| 1.192.86.205 | 503 | Amesbury | United States |
| 91.205.189.15 | 406 |  |  |
| 216.221.226.11 | 505 | Redwood City | United States |
| 216.221.226.11 | 404 | Redwood City | United States |
| 195.2.240.99 | 400 |  | Russia |

#### 3. Add a prefix to the fields added by the iplocation command

Prefix the fields added by the iplocation command with iploc_. Add all of the fields in the .mmdb database file to the results.

#### 4. Generate a choropleth map using IP addresses

Generate a choropleth map of your data like the one below using the iplocation command. See Use IP addresses to generate a choropleth map in Dashboards and Visualizations.

#### 5. Identify IPv6 address locations

The iplocation command supports IPv6 lookup through IP geolocation functionality. In the following example, iplocation looks up the specified IP address in the default geolocation database file to determine where it is located.

Search finds the location of the IP address and displays the following results.

| City | Country | Region | _time | lat | lon | myip |
| --- | --- | --- | --- | --- | --- | --- |
|  | United States |  | 2021-11-22 13:37:07 | 37.75100 | -97.82200 | 2001:4860:4860::8888 |
 