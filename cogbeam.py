''' Copyright 2020 Google LLC

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    https://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.'''

import apache_beam as beam
import os
import tempfile
import argparse
import logging
import fnmatch
from google.cloud import storage

import rasterio
from rio_cogeo.cogeo import cog_translate
from rio_cogeo.profiles import cog_profiles


def write_script():
	# Find all the exported COGs and add them to a sample Google Earth Engine Script
	storage_client = storage.Client()
	bucket_name = options['cog_bucket']
	cog_folder = options['cog_folder']
	blobs = storage_client.list_blobs(
		bucket_name, prefix=cog_folder, delimiter=None
	)
	script_name = 'gee-script.js'
	
	if not cog_folder:
			gcs_script_filename = 'gee-script.js'
	else:
		gcs_script_filename = cog_folder + "/" + script_name
	cog_uris = []
	for blob in blobs:
		if fnmatch.fnmatch(blob.name, "*.tif"):
			blob_uri = 'gs://{}/{}'.format(bucket_name,blob.name)
			cog_uris.append(blob_uri)

	var_tmpl = "var {image} = ee.Image.loadGeoTIFF('{uri}')\n"
	list_tmpl = "var list = [{images}]\n"
	img_coll = "var imageCollection = ee.ImageCollection.fromImages(list)\n"
	methods = """Map.addLayer(imageCollection);\nMap.centerObject(imageCollection,13)"""
	image_vars = ['image' + str(n) for n in range(len(cog_uris))]
	with open(script_name, 'w') as dest:
		for uri, image_var in zip(cog_uris, image_vars):
			dest.write(var_tmpl.format(image=image_var, uri=uri))
		dest.write(list_tmpl.format(images=', '.join(image_vars)))
		dest.write(img_coll)
		dest.write(methods)
	cog_bucket = storage_client.bucket(bucket_name)
	new_blob = cog_bucket.blob(gcs_script_filename)
	new_blob.upload_from_filename(script_name)

	script_uri = ('gs://{}/{}'.format(bucket_name, gcs_script_filename))
	logging.info('GEE Script uploaded to: {}'.format(script_uri))


def cogTranslate(src_path, dst_path, profile, profile_options={}, **options):
	# Convert image to COG.
	# Format creation option (see gdalwarp `-co` option)
	output_profile = cog_profiles.get(profile)
	output_profile.update(dict(BIGTIFF="IF_SAFER"))
	output_profile.update(profile_options)

	# Dataset Open option (see gdalwarp `-oo` option)
	config = dict(
		GDAL_NUM_THREADS="ALL_CPUS",
		GDAL_TIFF_INTERNAL_MASK=True,
		GDAL_TIFF_OVR_BLOCKSIZE="128",
	)

	cog_translate(
		src_path,
		dst_path,
		output_profile,
		config=config,
		in_memory=False,
		quiet=True,
		**options,
	)
	return True


def list_blobs(source_bucket, source_folder, file_pattern, delimiter=None):
	# Find all of the source GeoTIFFs and yield them to the pipeline
	storage_client = storage.Client()

	blobs = storage_client.list_blobs(
		source_bucket, prefix=source_folder, delimiter=delimiter
	)

	for blob in blobs:
		if fnmatch.fnmatch(blob.name, file_pattern):
			yield blob.name


class create_cog(beam.DoFn):
	# Download a GeoTIFF, including any potential sidecar files
	# Convert to a COG and upload to COG Export bucket
	def process(self, element):
		bucket_name = options['source_bucket']
		storage_client = storage.Client()
		potentialTFWName = element.replace('.tif','.tfw')
		potentialAUXName = element.replace('.tif','.aux')

		tfwExists = storage.Blob(bucket=storage_client.bucket(bucket_name), name=potentialTFWName).exists(storage_client)

		# Get TFW sidecar if one is present
		if tfwExists:
			blob = storage_client.bucket(bucket_name).get_blob(potentialTFWName)
			new_tfw_filename = element.split('/')[-1].replace('.tif','.tfw')
			blob.download_to_filename(new_tfw_filename)

		auxExists = storage.Blob(bucket=storage_client.bucket(bucket_name), name=potentialAUXName).exists(storage_client)

		# Get AUX sidecar if one is present
		if auxExists:
			blob = storage_client.bucket(bucket_name).get_blob(potentialAUXName)
			new_tfw_filename = element.split('/')[-1].replace('.tif','.aux')
			blob.download_to_filename(new_tfw_filename)

		# Now get the TIF 
		blob = storage_client.bucket(bucket_name).get_blob(element)
		new_tif_filename = element.split('/')[-1]
		cog_tif_filename = "cog_" + new_tif_filename
		blob.download_to_filename(new_tif_filename)

		logging.info('Image {} was downloaded to {}.'.format(str(element),new_tif_filename))

		# Convert to a COG
		createCog = cogTranslate(new_tif_filename,cog_tif_filename,options['profile'])

		# Upload to COG Export bucket
		cog_bucket_name = options['cog_bucket']
		cog_folder = options['cog_folder']
		if not cog_folder:
			gcs_cog_filename = cog_tif_filename
		else:
			gcs_cog_filename = options['cog_folder'] + "/" + cog_tif_filename
		cog_bucket = storage_client.bucket(cog_bucket_name)
		new_blob = cog_bucket.blob(gcs_cog_filename)
		new_blob.upload_from_filename(cog_tif_filename)
		cog_uri = ('gs://{}/{}'.format(cog_bucket_name,gcs_cog_filename))
		logging.info('COG version uploaded to: {}'.format(cog_uri))
		os.remove(new_tif_filename)
		os.remove(cog_tif_filename)
		logging.info('Local copies of source image and COG deleted')
		yield  cog_uri


def run_job(options):
	# Define the pipeline
	opts = beam.pipeline.PipelineOptions(flags=[], **options)
	p = beam.Pipeline(options['runner'], options=opts)
	
	sources = (
		p
		| beam.Create(list_blobs(options['source_bucket'],options['source_folder'],options['file_pattern']))
	)

	converted = (
		sources
		| 'Convert to COGs' >> beam.ParDo(create_cog())
	)

	# Run pipeline in blocking mode
	p.run().wait_until_finish()

	# Clean up Dataflow tmp / staging directories
	if not options['cog_folder']:
		prefix = "tmp"
	else:
		prefix = options['cog_folder'] + "/tmp"

	storage_client = storage.Client()
	temp_blobs = storage_client.list_blobs(options['cog_bucket'], prefix=prefix, delimiter=None)
	for blob in temp_blobs:
		logging.info("Deleting {}".format(blob.name))
		blob.delete()

	# Create a sample Google Earth Engine Script in the COG Bucket to view all the COGs
	write_script()

if __name__ == '__main__':
	parser = argparse.ArgumentParser(
	  description='Create Cloud Optimized GeoTIFFs from GeoTIFFs')
	parser.add_argument(
	  '--project', required=True, help='Specify GCP project where pipeline will run and usage will be billed')
	parser.add_argument(
	  '--cog_bucket', required=True, help='GCS Output Bucket ONLY (no folders) e.g. "bucket_name" for Converted COGs')
	parser.add_argument(
	  '--cog_folder', required=True, help='GCS Output Bucket folder(s) e.g. "folder_level1/folder_level2" for Converted COGs - can be blank for root of bucket')
	parser.add_argument(
	  '--source_bucket', required=True, help='GCS Source Bucket ONLY (no folders) e.g. "bucket_name"')
	parser.add_argument(
	  '--source_folder', required=True, help='GCS Bucket folder(s) e.g. "folder_level1/folder_level2"')
	parser.add_argument(
	  '--file_pattern', required=True, help='File pattern to search e.g. "*.tif"')
	parser.add_argument(
	  '--network', required=True, help='GCE Network to use')
	parser.add_argument(
	  '--profile',
	  default='lzw',
	  required=False,
	  help='COG Profile to use (jpeg, webp, lzw, deflate, etc.) JPEG is default but only supports 3 band rasters. WebP not well supported yet')
	parser.add_argument(
	  '--max_num_workers',
	  default=20,
	  required=False,
	  help='The maximum number of workers to scale to in the Dataflow pipeline')
	parser.add_argument(
	  '--machine_type',
	  default='n1-standard-2',
	  required=False,
	  help='The Compute Engine machine type to use for each worker')
	parser.add_argument(
	  '--region',
	  default='us-central1',
	  required=False,
	  help='The GCP region in which the pipeline will run')

	# Parse command-line args and add a few more
	logging.basicConfig(level=getattr(logging, 'INFO', None))
	options = parser.parse_args().__dict__
	cog_bucket = options['cog_bucket']
	cog_folder = options['cog_folder']

	if not cog_folder:
		staging_location = os.path.join('gs://',cog_bucket,'tmp', 'staging')
		temp_location = os.path.join('gs://',cog_bucket, 'tmp')
	else:
		staging_location = os.path.join('gs://',cog_bucket + "/" + cog_folder, 'tmp', 'staging')
		temp_location = os.path.join('gs://',cog_bucket + "/" + cog_folder, 'tmp')

	logging.info("Staging Location {}".format(staging_location))
	logging.info("Temp Location {}".format(temp_location))			

	options.update({
	  'staging_location':
		  staging_location,
	  'temp_location':
		  temp_location,
	  'job_name':
		  'cogbeam',
	  'teardown_policy':
		  'TEARDOWN_ALWAYS',
	  'setup_file':
		  os.path.join(os.path.dirname(os.path.abspath(__file__)), './setup.py'),
	  'save_main_session':
		  True,
	  'runner':
		  'DataflowRunner',		  
	})

	print('Launching Dataflow job {} ... hang on'.format(options['job_name']))

	run_job(options)
