#! /usr/bin/env python

'''
  DESCRIPTION: Execute test orders using the local environment.

  LICENSE: NASA Open Source Agreement 1.3
'''


import os
import sys
import socket
import logging
import json
from argparse import ArgumentParser

import sensor
import utilities


MODIS_HOST = 'e4ftl01.cr.usgs.gov'


def build_argument_parser():
    """Build the command line argument parser"""

    # Create a command line argument parser
    description = 'Configures and executes a test order'
    parser = ArgumentParser(description=description)

    # Add parameters
    parser.add_argument('--keep-log',
                        action='store_true', dest='keep_log', default=False,
                        help='keep the log file')

    parser.add_argument('--request',
                        action='store', dest='request', required=True,
                        help='request to process')

    parser.add_argument('--master',
                        action='store_true', dest='master', default=False,
                        help='use the master products file')

    parser.add_argument('--plot',
                        action='store_true', dest='plot', default=False,
                        help='generate plots')

    parser.add_argument('--pre',
                        action='store_true', dest='pre', default=False,
                        help='use a -PRE order suffix')

    parser.add_argument('--post',
                        action='store_true', dest='post', default=False,
                        help='use a -POST order suffix')

    return parser


def get_satellite_sensor_code(product_id):
    """Returns the satellite-sensor code if known"""

    old_prefixes = ['LT4', 'LT5', 'LE7',
                    'LT8', 'LC8', 'LO8',
                    'MOD', 'MYD']
    collection_prefixes = ['LT04', 'LT05', 'LE07',
                           'LT08', 'LC08', 'LO08']

    satellite_sensor_code = product_id[0:3]
    if satellite_sensor_code in old_prefixes:
        return satellite_sensor_code

    satellite_sensor_code = product_id[0:4]
    if satellite_sensor_code in collection_prefixes:
        return satellite_sensor_code

    raise Exception('Satellite-Sensor code ({0}) not understood'
                    .format(satellite_sensor_code))


# ============================================================================
def process_test_order(request_file, products_file, env_vars,
                       keep_log, plot, pre, post):
    """Process the test order file"""

    logger = logging.getLogger(__name__)

    template_file = 'template.json'
    template_dict = None

    tmp_order = 'tmp-test-order'

    order_id = (request_file.split('.json')[0]).replace("'", '')

    if pre:
        order_id = ''.join([order_id, '-PRE'])

    if post:
        order_id = ''.join([order_id, '-POST'])

    have_error = False
    status = True
    error_msg = ''

    products = list()
    if not plot:
        with open(products_file, 'r') as scenes_fd:
            while (1):
                product = scenes_fd.readline().strip()
                if not product:
                    break
                products.append(product)
    else:
        products = ['plot']

    logger.info('Processing Products [{0}]'.format(', '.join(products)))

    with open(template_file, 'r') as template_fd:
        template_contents = template_fd.read()
        if not template_contents:
            raise Exception('Template file [{0}] is empty'
                            .format(template_file))

        template_dict = json.loads(template_contents)
        if template_dict is None:
            logger.error('Loading template.json')

    for product_id in products:
        logger.info('Processing Product [{0}]'.format(product_id))

        sensor_inst = sensor.instance(product_id)
        sensor_code = sensor_inst.sensor_code.upper()

        with open(request_file, 'r') as request_fd:
            request_contents = request_fd.read()
            if not request_contents:
                raise Exception('Order file [{0}] is empty'
                                .format(request_file))

            logger.info('Processing Request File [{0}]'.format(request_file))

            request_dict = json.loads(request_contents)
            if request_dict is None:
                logger.error('Loading [{0}]'.format(request_file))

            # Merge the requested options with the template options, to create
            # a new dict with the requested options overriding the template.
            new_dict = template_dict.copy()
            new_dict.update(request_dict)
            new_dict['options'] = template_dict['options'].copy()
            new_dict['options'].update(request_dict['options'])

            # Turn it into a string for follow-on processing
            order_contents = json.dumps(new_dict, indent=4, sort_keys=True)

            with open(tmp_order, 'w') as tmp_fd:

                logger.info('Creating [{0}]'.format(tmp_order))

                tmp_line = order_contents

                # Update the order for the developer
                download_url = 'null'
                is_modis = False
                if sensor_code in ['MOD', 'MYD']:
                    is_modis = True

                # for plots
                if not is_modis and not plot:
                    product_path = ('{0}/{1}/{2}{3}'
                                    .format(env_vars['dev_data_dir']['value'],
                                            sensor_code, product_id,
                                            '.tar.gz'))

                    logger.info('Using Product Path [{0}]'
                                .format(product_path))
                    if not os.path.isfile(product_path):
                        error_msg = ('Missing product data [{0}]'
                                     .format(product_path))
                        have_error = True
                        break

                    download_url = 'file://{0}'.format(product_path)

                elif not plot:
                    if sensor_code == 'MOD':
                        base_source_path = '/MOLT'
                    else:
                        base_source_path = '/MOLA'

                    short_name = sensor.instance(product_id).short_name
                    version = sensor.instance(product_id).version
                    archive_date = utilities.date_from_doy(
                        sensor.instance(product_id).year,
                        sensor.instance(product_id).doy)
                    xxx = ('{0}.{1}.{2}'
                           .format(str(archive_date.year).zfill(4),
                                   str(archive_date.month).zfill(2),
                                   str(archive_date.day).zfill(2)))

                    product_path = ('{0}/{1}.{2}/{3}'
                                    .format(base_source_path, short_name,
                                            version, xxx))

                    if sensor_code == 'MOD' or sensor_code == 'MYD':
                        download_url = ('http://{0}/{1}/{2}.hdf'
                                        .format(MODIS_HOST, product_path,
                                                product_id))

                sensor_name = 'plot'
                if not plot:
                    sensor_name = sensor.instance(product_id).sensor_name
                    logger.info('Processing Sensor [{0}]'.format(sensor_name))
                else:
                    logger.info('Processing Plot Request')

                tmp_line = tmp_line.replace('\n', '')
                tmp_line = tmp_line.replace('ORDER_ID', order_id)
                tmp_line = tmp_line.replace('SCENE_ID', product_id)

                if sensor_name in ['tm', 'etm', 'olitirs']:
                    tmp_line = tmp_line.replace('PRODUCT_TYPE', 'landsat')
                elif sensor_name in ['terra', 'aqua']:
                    tmp_line = tmp_line.replace('PRODUCT_TYPE', 'modis')
                else:
                    tmp_line = tmp_line.replace('PRODUCT_TYPE', 'plot')

                tmp_line = tmp_line.replace('DOWNLOAD_URL', download_url)

                tmp_fd.write(tmp_line)

                # Validate again, since we modified it
                parms = json.loads(tmp_line)
                print(json.dumps(parms, indent=4, sort_keys=True))

            # END - with tmp_order
        # END - with request_file

        if have_error:
            logger.error(error_msg)
            return False

        keep_log_str = ''
        if keep_log:
            keep_log_str = '--keep-log'

        cmd = ('cd ..; cat test-orders/{0} | ./ondemand_mapper.py {1}'
               .format(tmp_order, keep_log_str))

        output = ''
        try:
            logger.info('Processing [{0}]'.format(cmd))
            output = utilities.execute_cmd(cmd)
            if len(output) > 0:
                print output
        except Exception, e:
            logger.exception('Processing failed')
            status = False

    os.unlink(tmp_order)

    return status


def main():
    """Main code for executing a test order"""

    logging.basicConfig(format=('%(asctime)s.%(msecs)03d %(process)d'
                                ' %(levelname)-8s'
                                ' %(filename)s:%(lineno)d:%(funcName)s'
                                ' -- %(message)s'),
                        datefmt='%Y-%m-%d %H:%M:%S',
                        level=logging.DEBUG)

    logger = logging.getLogger(__name__)

    # Build the command line argument parser
    parser = build_argument_parser()

    env_vars = dict()
    env_vars = {'dev_data_dir': {'name': 'DEV_DATA_DIRECTORY',
                                 'value': None}}

    missing_environment_variable = False
    for var in env_vars:
        env_vars[var]['value'] = os.environ.get(env_vars[var]['name'])

        if env_vars[var]['value'] is None:
            logger.warning('Missing environment variable [{0}]'
                           .format(env_vars[var]['name']))
            missing_environment_variable = True

    # Terminate if missing environment variables
    if missing_environment_variable:
        logger.critical('Please fix missing environment variables')
        sys.exit(1)  # EXIT_FAILURE

    # Parse the command line arguments
    args = parser.parse_args()

    request_file = '{0}.json'.format(args.request.replace("'", "\'"))
    if not os.path.isfile(request_file):
        logger.critical('Request file [{0}] does not exist'
                        .format(request_file))
        sys.exit(1)  # EXIT_FAILURE

    products_file = None
    if not args.plot:
        products_file = '{0}.products'.format(args.request)

        if args.master:
            # Use the master file instead
            products_file = '{0}.master.products'.format(args.request)

        if not os.path.isfile(products_file):
            logger.critical('No products file exists for [{0}]'
                            .format(args.request))
            sys.exit(1)  # EXIT_FAILURE

    # Avoid the creation of the *.pyc files
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'

    if not process_test_order(request_file, products_file, env_vars,
                              args.keep_log, args.plot, args.pre, args.post):
        logger.critical('Request [{0}] failed to process'.format(args.request))
        sys.exit(1)  # EXIT_FAILURE

    sys.exit(0)  # EXIT_SUCCESS


if __name__ == '__main__':
    main()
