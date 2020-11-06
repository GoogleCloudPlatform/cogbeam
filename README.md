![banner](https://storage.googleapis.com/cogbeam-images/cogbeam.png)

# cogbeam

This is not an officially supported Google product, though support will be provided on a best-effort basis.

Copyright 2020 Google LLC

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    https://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

## Introduction

cogbeam is a simple python based [Apache Beam](https://beam.apache.org/) pipeline, optimized for [Google Cloud Dataflow](https://cloud.google.com/dataflow), which aims to expedite the conversion of traditional GeoTIFFs into [Cloud Optimized GeoTIFFS](https://www.cogeo.org/) by leveraging on-demand parallel processing. 

The impetus for cogbeam came from [Google Earth Engine's](https://earthengine.google.com/) (GEE) support of COGs as [Cloud GeoTIFF Backed Earth Engine Assets](https://developers.google.com/earth-engine/Earth_Engine_asset_from_cloud_geotiff) as a means for users of GEE to analyze raster data in situ, directly from [Google Cloud Storage ](https://cloud.google.com/storage) (GCS). 

There are decades worth of raster geospatial data that could easily be made accessible and made ready for analysis if it were converted to the open COG standard, and it would be a drag to have to do all of that using [gdal_translate](https://gdal.org/) in serial.  

Therefore, cogbeam is designed to simply point to bucket of regular geotiffs in a GCS bucket, specify a new bucket where you'd like your COGs to appear, spin up an appropriate number of workers to batch convert your geotiffs into COGs and then immediately shut down those workers. At that point you can delete the source images for cost savings. 

## Preparation

### Clone this repository and configure Cloud Shell or a Compute Engine Virtual Machine to launch Dataflow Pipelines
**Note:** Cloud Shell is limited to sessions that are less than 20 minutes. If you're running a large conversion pipeline that is likely to take more than 20 minutes, use [tmux](https://github.com/tmux/tmux/wiki) and a Virtual Machine on [Compute Engine](https://cloud.google.com/compute).

Choose a [Google Cloud Platform project](https://cloud.google.com/resource-manager/docs/creating-managing-projects) where you will launch this Dataflow pipeline. 

#### If running in a VM

You don't need much of a machine to launch the pipeline as none of the processing of the pipeline is done locally.

1. Start with an Ubuntu 20.04 Image
2. start a tmux session (this will ensure that your pipeline finishes correctly even if you lose connection to your VM). `tmux` 
3. Update aptitude. `sudo apt-get update`
4. Install pip3 `sudo apt-get install python3-pip`
5. Clone this repository `git clone XXXXXX`
6. Change directories into the new "cogbeam" folder: `cd cogbeam`
7. Install local python3 dependencies `pip install -r requirements.text`
8. You'll need to authenticate so that the python code that runs locally can use your credentials. `gcloud auth application-default login`


#### If running in Cloud Shell

1. Launch a [Cloud Shell](https://cloud.google.com/shell) from that project.
2. Clone this repository: `git clone XXXXXXXX`
3. Change directories into the new "cogbeam" folder: `cd cogbeam`
4. You will need to install the python dependencies locally: `pip3 install -r requirements.text`

### Configure the Default Network

By default, GCP projects will automatically create a VPC network called 'default' upon creation that have a subnet in each region. However, some organizations have policies that prohibit the creation of a default network. You can check to see if you already have a 'default' or other VPC network in your project [here](https://console.cloud.google.com/networking/networks/list?). If you already have a network in the project, you can skip this step. Otherwise, you'll want to create a VPC network. 

Click "CREATE VPC NETWORK"

![](https://storage.googleapis.com/cogbeam-images/vpc1.png)

Choose a name for the network. ('default' is fine, you'll just need to remember what it is later when you launch the pipeline.)

Choose 'Automatic' for the 'Subnet creation mode'.

![](https://storage.googleapis.com/cogbeam-images/vpc2.png)

Select some of the default Firewall rules for the network, but at least choose **"default-allow-internal"** so the workers can communicate with each other. Note: this example only really worries about running Dataflow; you may have other requirements. 

![](https://storage.googleapis.com/cogbeam-images/vpc3.png)

Choose 'Regional' for the Dynamic routing mode. Click 'Create' to create the network.

![](https://storage.googleapis.com/cogbeam-images/vpc4.png)


### Enable the Dataflow API  

You need to enable the Dataflow API for your project [here](https://console.developers.google.com/apis/api/dataflow.googleapis.com/overview).

Click "Enable"

![](https://storage.googleapis.com/cogbeam-images/dataflowapi1.png)

### Source and Destination Bucket Permission Considerations
If you're running cogbeam in a project your account owns, there shouldn't be anything special that you need to do with regard to permissions on either the source or destination GCS Buckets.

However, you may wish to read from GCS buckets in another GCP project, and write to buckets in another project. If so, you'll need to consider the following permission requirements, and make sure the following accounts have the following minimum permissions on the buckets.

* Source Bucket 
	* Storage Object Viewer	
		* Your project's [Compute Engine default service account](https://cloud.google.com/dataflow/docs/concepts/security-and-permissions#controller_service_account)
			* Because the Dataflow workers need to be able to read the source bucket and find the source images. 
* Destination Bucket
	* Storage Object Admin 
		* Your Google account
			* Because you have to upload the staging files to launch the Dataflow pipeline 
		* Your project's Compute Engine default service account
			* Because the Dataflow workers need to be able to write and delete objects to/from the destination bucket. 

Also, before running cogbeam, if you want the resulting COGs to be publicly available you should add the account 'allUsers' as a Storage Object Viewer on the bucket as discussed [here](https://cloud.google.com/storage/docs/access-control/making-data-public). That way, every COG generated will automatically be publicly viewable. 
		

By default, workers use your project's Compute Engine default service account as the controller service account. This service account (<project-number>-compute@developer.gserviceaccount.com) is automatically created when you enable the Dataflow API for a project. You can verify this service account exists and find it's full address under the [IAM & Admin section of your project.](https://console.cloud.google.com/iam-admin/iam?) 	 	


## Usage

`python3 cogbeam.py -h`

| Flag              | Required | Default       | Description                                                                                                                        |
|-------------------|----------|---------------|------------------------------------------------------------------------------------------------------------------------------------|
| --project         | Yes      |               | Specify GCP project where pipeline will run and usage will be billed                                                               |
| --cog\_bucket      | Yes      |               | GCS Output Bucket ONLY (no folders) e.g. "bucket_name" for Converted COGs                                                          |
| --cog\_folder      | Yes      |               | GCS Output Bucket folder(s) e.g. "folder\_1/folder\_2" for Converted COGs - can be blank for root of bucket                |
| --source\_bucket   | Yes      |               | GCS Source Bucket ONLY (no folders) e.g. "bucket_name"                                                                             |
| --source\_folder   | Yes      |               | GCS Bucket folder(s) e.g. "folder\_1/folder\_2"                                                                            |
| --file\_pattern    | Yes      |               | File pattern to search e.g. "*.tif"                                                                                                |
| --network         | Yes      |               | GCE Network to use                                                                                                                 |
| --profile         | No       | lzw           | COG Profile to use (jpeg, webp, lzw, deflate, etc.) JPEG is default but only supports 3 band rasters. WebP not well supported yet. |
| --max\_num\_workers | No       | 20            | The maximum number of workers to scale to in the Dataflow pipeline.                                                                |
| --machine\_type    | No       | n1-standard-2 | The Compute Engine [machine type](https://cloud.google.com/compute/docs/machine-types) to use for each worker                                                                             |
| --region          | No       | us-central1   | The [GCP region](https://cloud.google.com/compute/docs/regions-zones#available) in which the pipeline will run                                                                 |

## Example

This example shows using cogbeam to convert the 812 regular GeoTIFFs from the 2016 NAIP for the US state of Vermont,located in the publicly accessible gs://vermont-naip-2016 bucket, into 812 COGs located in the publicly accessible gs://vermont-naip-2016-cog bucket. 

`python3 cogbeam.py --source_bucket "vermont-naip-2016" --source_folder "" --file_pattern "*.tif" --cog_bucket "vermont-naip-2016-cog" --cog_folder "" --network default --project cogbeam --profile lzw`

The pipeline should start off by uploading the staging files to the '\tmp' directory of your 'cog_bucket' folder and then you will get a link to track the pipeline in the GCP console. The 'Job status' will be 'Running.'

![](https://storage.googleapis.com/cogbeam-images/dataflow1.png)

You'll also see a constant stream of communication from Dataflow in your terminal window, as the pipeline scales workers up and down to handle the conversion of the COGs. 

![](https://storage.googleapis.com/cogbeam-images/dataflow2.png)

When the pipeline completes, all the workers will be turned down and you should see the 'Job status' as 'Succeeded.'

![](https://storage.googleapis.com/cogbeam-images/dataflow3.png)

### Result

At the end of the script, a sample Google Earth Engine script is generated and uploaded to the cog_bucket. In this example, it is uploaded to: [gs://vermont-naip-2016-cog/gee-script.js](https://storage.googleapis.com/vermont-naip-2016-cog/gee-script.js)

You can simply cut and paste the contents of that script to examine the COGs in Google Earth Engine.

![](https://storage.googleapis.com/cogbeam-images/vt-naip-2016-cog1.png)
View the Vermont 2016 NAIP Imagery as COGs in [Google Earth Engine here](https://code.earthengine.google.com/0e2cb04304bc11eb96ac9fcf6c8b5104) (Google Earth Engine Access Required)

But don't forget, these are 4 band COGs, and Google Earth Engine isn't just for visualization. You can treat a COG in GEE just like a native asset so it's easy to create an NDVI analysis against the COGs without moving them from Google Cloud Storage. 

![](https://storage.googleapis.com/cogbeam-images/vt-naip-2016-cog2.png)
[View this GEE script.](https://code.earthengine.google.com/8ffe2ce1754b8fbcb2c7b1519e101243?hideCode=true) Note: there is a slight delay when using COGs as GEE has to read all of the headers to understand their metadata. 

## Cost Considerations
*These figures are estimates using GCP pricing as of 10/2020

Generating COGs slightly increases the size of each file because it adds tiled overviews to the GeoTIFFs. Below we'll review some of the costs for the 2016 Vermont NAIP example. 


|    Image Type    | Storage Size | Monthly Storage Cost (us multiregion) |
|:----------------:|--------------|---------------------------------------|
| Standard GeoTIFF |  295.32 GiB  |                                 $7.68 |
| COG              |  440.21 GiB  |                                $11.45 |

Running the Dataflow pipeline, with 20 n1-standard-2 machines resulted in the following billable metrics for the 27 minute 11 second run. 

|       Metric      | Count           |
|:-----------------:|-----------------|
| Total vCPU time   |  12.594 vCPU hr |
| Total memory time |   47.227 GB hr  |
| Total HDD PD time | 1,574.233 GB hr |

This equates to roughly $1.44 in processing costs for the conversion. 

A final consideration is egress. When you're sharing datasets on cloud storage, presumably it is so analysts can access it. It can be extremely difficult though to figure out how many analysts will download the data, and how much of it, over the course of a year. Once a dataset leaves any cloud provider's network you are charged an egress fee. These costs can mount quickly and unpredictably. Here's a table showing the estimated egress charges for the example dataset in terms of number of times the entire dataset is downloaded. 

| Number of Downloads | Price   |
|---------------------|---------|
|          1          | $31.01  |
|          2          | $62.02  |
|          5          | $155.05 |
|          10         | $310.10 |

We can look at similar estimates for the slightly larger COGs, which are backwards compatible and somewhat likely to still be downloaded for some applications.  But, an important difference with COGs is that they're already "analysis ready" as we've shown with Google Earth Engine. That means that end users of the data don't actually have to download the data off of the cloud - they can analyze it in place and on GCP, that doesn't represent a billable egress event.  

| Number of Downloads | Price  |
|---------------------|--------|
|          1          | $46.22 |
|          2          | $92.44 |
|   COGs used in GEE  | $0     |

