#define BOOST_MPL_CFG_NO_PREPROCESSED_HEADERS
#define BOOST_MPL_LIMIT_VECTOR_SIZE 30
#define CLEAR_RESAND_NUM 1
#define FPS_CALC_LENGTH 20
#define GUI_BUILD_TXLGU
#include "sensor_msgs/CompressedImage.h"
#include "sensor_msgs/Image.h"
#include <image_transport/image_transport.h>
#include <opencv2/imgproc/imgproc.hpp>
#include <opencv2/highgui/highgui.hpp>
#include <cv_bridge/cv_bridge.h>
#include <sensor_msgs/image_encodings.h>
#include <ros/ros.h>
#include <arbe_msgs/arbeNewPcMsg.h>
#include <arbe_msgs/arbePcFloatMsg.h>
#include <arbe_msgs/arbePcFloatBins.h>
#include <arbe_msgs/arbePcFlagBitsEnum.h>
#include <arbe_msgs/arbeGUIsettings.h>
#include <arbe_msgs/arbeSlamDisplaySettings.h>
#include <arbe_msgs/arbeCameraInstallationParams.h>
#include <arbe_msgs/arbeSlamMsg.h>
#include <arbe_msgs/arbeRdInclination.h>
#include <arbe_msgs/wfObjectMsg.h>
#include <arbe_msgs/wfSObj.h>
#include <arbe_msgs/wfImuData.h>
#include <std_msgs/Float32MultiArray.h>
#include <std_msgs/Float32.h>
#include <std_msgs/UInt32.h>
#include <std_msgs/UInt32MultiArray.h>
#include <std_msgs/Float32MultiArray.h>
#include <std_msgs/Bool.h>
#include <arbe_msgs/wfRawDataMsg.h>
#include <arbe_msgs/wfTiFrameRD.h>
#include <arbe_msgs/wfCarDataMsg.h>
#include <arbe_msgs/wfCar_id6DataMsg.h>
#include <arbe_msgs/VehStatusOutput.h>
#include <arbe_msgs/ImuOutput.h>
#include <arbe_msgs/wfTiRDdata.h>
#include <arbe_msgs/wfAutosarData.h>
#include <wf_srvs_rvizbag/PlaySingleFrame.h>
#include <geometry_msgs/PolygonStamped.h>
#include <algorithm>
#include <vector>
#include <visualization_msgs/MarkerArray.h>
#include <tf2_geometry_msgs/tf2_geometry_msgs.h>
#include "Slam_color.hpp"
#include "Pointcloud_coloring.hpp"
#include "vis_utils.hpp"
#include "arbe_msgs/arbeBoolWithTime.h"
#include "visualization_node.h"
#include <mutex>
#include <ros/callback_queue.h>
#include <cmath>
#include <algorithm>
#include <std_msgs/String.h>
#include <fstream>
#include <ctime>
#include <unistd.h>
#include <math.h>
#define MAX_RADARS (10)
#define QUEUE_FOR_PC (5)
#define QUEUE_FOR_CAMERA (3)
#define IND_FOR_PC_MAIN 0
#define IND_FOR_CAM_MAIN 0
#define IND_FOR_PC_OBJ 1
#define IND_FOR_CAM_OBJ 1
#define IND_FOR_PC_FS 2
#define IND_FOR_CAM_NEIGHBOR 2
#define IND_FOR_PC_INJECT 3
#define IND_FOR_PC_SUB 4
#define DEG_TO_RAD (0.017444)
static arbe_msgs::arbePcFloatMsg::ConstPtr DynPointCloudMsg_global;
static arbe_msgs::arbePcFloatMsg::ConstPtr StationaryPointCloudMsg_global;
static arbe_msgs::arbeSlamDisplaySettings slamDisplaySettings;
static arbe_msgs::wfObjectMsg ObjectListMsg_global;
static arbe_msgs::wfObjectMsg algo_object_list_for_display;
static ros::Subscriber pc_frame_sub;
static ros::Publisher arbe_pc_frame_pub;
static ros::Subscriber gui_commands_sub;
static ros::Subscriber targets_sub;
static ros::Subscriber targets_legacy_sub;
static ros::Subscriber stationary_targets_sub;
static ros::Subscriber objects_sub;
static ros::Subscriber objects_cam_sub;
static ros::Subscriber master_slam_sub;
static ros::Subscriber gui_controls_sub;
static ros::Subscriber slam_active_sub;
static ros::Subscriber enable_legacy_pc_inject_sub;
static ros::Subscriber fs_display_sub;
static ros::Subscriber camera_params_sub;
static ros::Subscriber FS_road_inclination_sub;
static ros::Subscriber installation_error_fix_sub;
static ros::Subscriber restore_defaults_sub;
static ros::Subscriber disp_FS_on_pc_sub;
static ros::Subscriber floating_text_angle_sub;
static ros::Subscriber radars_installation_params_sub;
static ros::Subscriber extra_time_single_color_sub;
static ros::Subscriber neighbor_slam_objects_sub[MAX_RADARS];
static ros::Subscriber radars_install_params_sub[MAX_RADARS];
static bool is_valid_neighbor[MAX_RADARS];
static bool was_radar_install_parmas_rcv[MAX_RADARS];
static radar_install_params neighbor_radar_install_params[MAX_RADARS];
static arbe_msgs::arbeSlamMsg neighbor_msg[MAX_RADARS];
static Eigen::Affine3f nbr_transform[MAX_RADARS];
static float delta_phi[MAX_RADARS];
static ros::Publisher arbe_bin_detections_pub;
static ros::Publisher arbe_slam_pub;
static ros::Publisher arbe_pcl_pub;
static ros::Publisher stationary_pcl_pub;
static ros::Publisher marker_pub;
static ros::Publisher fs_poly_pub;
static ros::Publisher slam_enable_pub;
static ros::Publisher free_space_enable_pub;
static ros::Publisher wf_bbox_pub;
static ros::Publisher wf_bbox_arrows_pub;
static ros::Publisher wf_bbox_referPt_pub;
static ros::Publisher wf_bbox_roadmaps_line_pub;
static ros::Publisher wf_bbox_roadmaps_point_pub;
static ros::Publisher wf_bbox_roadmapsFit_line_pub;
static ros::Publisher wf_bbox_roadmapsFit_point_pub;
static ros::Publisher wf_bbox_tags_pub;
static ros::Publisher wf_cluster_bbox_pub;
static ros::Publisher wf_bsd_area_pub;
static ros::Publisher wf_lca_area_pub;
static ros::Publisher wf_dow_area_pub;
static ros::Publisher wf_rcw_area_pub;
static ros::Publisher wf_rcta_area_pub;
static ros::Publisher wf_fcta_area_pub;
static ros::Publisher wf_curb_area_pub;
static ros::Publisher wf_adas_warn_status_pub;
static ros::Publisher wf_adas_warn_status_with_frame_pub;
static visualization_msgs::MarkerArray wf_bsd_area;
static visualization_msgs::MarkerArray wf_lca_area;
static visualization_msgs::MarkerArray wf_rcta_area;
static visualization_msgs::MarkerArray wf_dow_area;
static visualization_msgs::MarkerArray wf_rcw_area;
static visualization_msgs::MarkerArray wf_fcta_area;
static visualization_msgs::MarkerArray wf_curb_area;
static std_msgs::UInt8MultiArray adas_warn_status;
static std_msgs::UInt32MultiArray adas_warn_status_with_frame;
static ros::Publisher wf_objectlist_pub;
static ros::Subscriber raw_cam_sub;
static ros::Subscriber gige_cam_sub;
static ros::Subscriber raw_cam_legacy_sub;
static ros::Subscriber gige_cam_legacy_sub;
static ros::Publisher arbe_capture_pub;
static ros::Publisher arbe_info_markers;
static ros::Publisher arbe_fps_pub;
static geometry_msgs::PolygonStamped FS_display_polygon;
static Eigen::Affine3f camera_transform = Eigen::Affine3f::Identity();
static Eigen::Affine3f pcl_transform = Eigen::Affine3f::Identity();
static arbe_msgs::arbeSlamMsg::ConstPtr slamMsg;
static arbe_msgs::arbeSlamMsg::ConstPtr masterSlamMsg;
static arbe_msgs::arbeSlamMsg::ConstPtr slamMsg_cam;
static ros::Subscriber wf_point_cloud_Sub;
static ros::Subscriber corner_radar_parsed_point_cloud_Sub;
static ros::Subscriber corner_radar_post_process_data_Sub;
static ros::Subscriber corner_radar_controls_Sub;
static ros::Subscriber egoCarSpdCoef_Sub;
static ros::Subscriber imu_data_Sub;
static ros::Subscriber daisch_imu_data_Sub;
static ros::Subscriber calibUpdateInfo_sub;
static ros::Subscriber bcalibPlateData_sub;
static ros::Subscriber car_vec_data_Sub;
static ros::Subscriber car_id6_vec_data_Sub;
static ros::Subscriber car_id6_vec_data_Sub1;
static ros::Subscriber car_id6_vec_data_Sub2;
static ros::Subscriber ti_RD_data_Sub;
static ros::Publisher corner_radar_pcl_pub;
static ros::Publisher corner_radar_algo_pub;
static ros::Publisher corner_radar_bbox_pub;
static ros::Publisher corner_radar_objectlist_pub;
static ros::Publisher corner_radar_info_pub;
static ros::Publisher bld_warning_info_pub;
static wf_srvs_rvizbag::PlaySingleFrame plsySingleFrameSrv;
static ros::ServiceClient play_single_frame_client;
static bool is_slam_frame_available = false;
static bool is_master_slam_frame_available = false;
static bool is_cam_slam_frame_available = false;
static bool is_pc_frame_available = false;
static bool is_clear_PC_frame_on = false;
static bool is_FS_display_active = false;
static bool is_cam_frame_available = false;
static bool is_slam_active = false;
static bool floating_text_enabled = false;
static bool expunge_text = false;
static bool enable_gui = true;
static bool terminating = false;
static sRdInclination rd_inc;
static visualization_msgs::MarkerArray slam_boxes;
static visualization_msgs::MarkerArray slam_arrows;
static visualization_msgs::MarkerArray slam_tags;
static visualization_msgs::MarkerArray wf_object_boxes;
static visualization_msgs::MarkerArray wf_object_referPt;
static visualization_msgs::MarkerArray wf_object_arrows;
static visualization_msgs::MarkerArray wf_object_roadmaps_line;
static visualization_msgs::MarkerArray wf_object_roadmaps_point;
static visualization_msgs::MarkerArray wf_object_roadmapsFit_line;
static visualization_msgs::MarkerArray wf_object_roadmapsFit_point;
static visualization_msgs::MarkerArray wf_object_tags;
// 录制 SGU 的独立显示缓存。它不参与 PostProcessMainTI 的输入或输出。
struct RawSguDisplayObject
{
	uint16_t obj_id;
	uint8_t obj_type;
	uint8_t dyn_flag;
	float x;
	float y;
	float yaw;
	float length;
	float width;
	float vel_x;
	float vel_y;
	float vel_abs_x;
	float vel_abs_y;
	float f_ttc;
	float f_ddci;
};
constexpr int64_t kRawSguObjectListIdBase = 1000000;
static std::vector<RawSguDisplayObject> raw_sgu_display_objects;
static visualization_msgs::MarkerArray wf_raw_sgu_object_boxes;
static visualization_msgs::MarkerArray wf_raw_sgu_object_tags;
static visualization_msgs::MarkerArray wf_cluster_boxes;
static visualization_msgs::MarkerArray wf_imu_object_boxes;
static visualization_msgs::Marker dtections_per_frame_marker;
static ros::Subscriber calibPlateData_sub;
static ros::Publisher calibResult_pub;
static std_msgs::Float32MultiArray calib_result_msg;
static std_msgs::Float32MultiArray algo_calibOutputInfo_msg;
static std_msgs::Float32MultiArray algo_calibInputInfo_msg;
static std_msgs::Float32MultiArray algo_calibUpdateInfo_msg;
static ros::Publisher calibInputInfo_pub;
static ros::Publisher calibOutputInfo_pub;
static ros::Publisher calibUpdateInfo_pub;
static bool FS_in_use = false;
static bool aggOnlyCoreStat = true;
static std::string ColoringType = "Elevation";
static std::string ColoringType_Record = "Elevation";
static bool disp_processed_pc = false;
static bool triggered_slam = true;
static bool set_disp_run_once = false;
static bool is_pc_display_on = true;
static bool is_processed_pc_display_on = true;
static bool read_legacy_processed_pc = false;
static float power_hash_table[512][2000];
static bool transformed_FS_in_use = false;
static geometry_msgs::PolygonStamped transformed_FS_polygon;
static bool fs_from_gui = true;
static Eigen::Affine3f extrinsic = Eigen::Affine3f::Identity();
static float prj[3][4] = {{1526.97, 0, 934.05, 18.68},
						  {0, 1533.03, 537.37, 133.39},
						  {0, 0, 1, 0.02}};
static bool disp_objects = false;
static sensor_msgs::CompressedImage::ConstPtr cam_image;
static std::mutex avaliable_frmae_mutex;
static uint64_t t_vec[FPS_CALC_LENGTH];
static size_t write_i_t = 0;
static size_t read_i_t = 0;
static uint8_t n_fps = 0;
static std::string radar_descriptor;
static uint32_t one_color_frame = 0;
static Eigen::Affine3f slam_transform = pcl_transform;
static Eigen::Affine3f *transform_p = &pcl_transform;
static uint32_t total_pts = 0;
static bool clear_stationary_once = true;
static uint32_t stationary_n_detections = 0;
static int16_t classes_to_show = -1;
static bool colorObjectsByClass = false;
static Eigen::Matrix3f intrinsic;
static int8_t primitive[2] = {-1, 1};
static uint8_t pr_x[8] = {0, 1, 1, 0, 0, 1, 1, 0};
static uint8_t pr_y[8] = {0, 0, 1, 1, 0, 0, 1, 1};
static uint8_t pr_z[8] = {0, 0, 0, 0, 1, 1, 1, 1};
static float scale_ref, rows_offset, cols_offset;
static ros::CallbackQueue pc_disp_queue[QUEUE_FOR_PC];
static ros::CallbackQueue cam_disp_queue[QUEUE_FOR_CAMERA];
static float s_menuAziValue = 0.0;
static float s_menuEleValue = 0.0;
float point_range_record = 0;
float point_doppler_record = 0;
const float point_epsinon = 0.000001f;
bool should_record_bld_warning = false;

bool algo_InitFlg_recoredBLD = true;
std::string RecordFileName = "bagname";
std::string current_csv_path;
static bool header_written = false;
static int g_last_bag_switch_epoch = -1;
static ros::Subscriber bld_warning_record_control_sub;
void write_bld_event_to_csv(const std::string &type,
							float carV,
							int frame_id,
							int radar_id);
typedef enum GNSS_GPCHC_INDEX
{
	GNSS_GPCHC_INDEX_HEADER = 0,
	GNSS_GPCHC_INDEX_GPSWEEK,
	GNSS_GPCHC_INDEX_GPSTime,
	GNSS_GPCHC_INDEX_HEADING,
	GNSS_GPCHC_INDEX_PICH,
	GNSS_GPCHC_INDEX_ROLL,
	GNSS_GPCHC_INDEX_GRRO_X,
	GNSS_GPCHC_INDEX_GRRO_Y,
	GNSS_GPCHC_INDEX_GRRO_Z,
	GNSS_GPCHC_INDEX_ACC_X,
	GNSS_GPCHC_INDEX_ACC_Y,
	GNSS_GPCHC_INDEX_ACC_Z,
	GNSS_GPCHC_INDEX_LAT,
	GNSS_GPCHC_INDEX_LON,
	GNSS_GPCHC_INDEX_ALT,
	GNSS_GPCHC_INDEX_VE,
	GNSS_GPCHC_INDEX_VN,
	GNSS_GPCHC_INDEX_VU,
	GNSS_GPCHC_INDEX_SPEED,
	GNSS_GPCHC_INDEX_NSV1,
	GNSS_GPCHC_INDEX_NSV2,
	GNSS_GPCHC_INDEX_STATUS,
	GNSS_GPCHC_INDEX_AGE,
	GNSS_GPCHC_INDEX_WARMING,
	GNSS_GPCHC_INDEX_MAX
} GNSS_GPCHC_INDEX;
int Trc_OutNum = 0;
int DotNumPstPrced = 0;
double TimeStamp = 0.0;
double RosbagTimeStamp = 0.0;
double CarInfoTimeStamp = 0.0;
int source_point_cloud_num = 0;
int waveIDG = 0;
static ros::Subscriber ti_frame_rd_data_Sub;
std::string fileNameWFObj = "testObjectData.json";
void GetWaveID(const arbe_msgs::wfTiFrameRD::ConstPtr &msg);
void calc_transform_matrix();
void calc_Coloring();
void set_colorObjByClass(bool flag);
int16_t get_classes_to_show();
void fs_display_handler();
void reset_fps_calc();
void one_color_add(uint32_t n_frames = 10);
void *radar_ethernet_logger_thread(void *args);
void targets_read_callback(const arbe_msgs::arbePcFloatMsg::ConstPtr &pcMsg, int pc_type);
void legacy_target_read_callback(const arbe_msgs::arbeNewPcMsg::ConstPtr &LegacyPcMsg, int pc_type);
void imu_targets_read_callback(const arbe_msgs::ImuOutput::ConstPtr &msg);
void corner_radar_post_process_data_callback(const arbe_msgs::wfAutosarData::ConstPtr &msg);
void wf_object_display_handler();
void update_raw_sgu_display_cache();
void wf_raw_sgu_object_display_handler();
void publish_raw_sgu_object_list();
void clear_wf_algorithm_object_markers();
void clear_raw_sgu_object_markers();
void wf_cluster_display_handler();
void wf_adas_display_handler();
void wf_curb_display_handler();
void slam_read_callback(const arbe_msgs::arbeSlamMsg::ConstPtr &msg);
void slam_read_cam_callback(const arbe_msgs::arbeSlamMsg::ConstPtr &msg);
void FS_disp_CB(const geometry_msgs::PolygonStamped::ConstPtr &FS_disp);
void calc_camera_intrinsic(const arbe_msgs::arbeCameraInstallationParams::Ptr &msg);
void calc_camera_extrinsic(const arbe_msgs::arbeCameraInstallationParams::Ptr &msg);
void calc_nbr_transform_matrix(uint8_t nbr, float dphi, float dpitch, float dx, float dy, float dz);
bool save_obj_json();
void reSetCarData();
void hardResetForBagSwitchIfNeeded();
void save_algo_data_csv();
void *sohandle;
void spin_pc_display()
{
	for (int i = 0; i < QUEUE_FOR_PC; i++)
	{
		pc_disp_queue[i].callAvailable();
	}
}
void spin_cam_display()
{
	for (int i = 0; i < QUEUE_FOR_CAMERA; i++)
	{
		cam_disp_queue[i].callAvailable();
	}
}
float get_egoVel()
{
	if (get_slam_valid())
		return slamMsg->meta_data.HostVelocity;
	return 0;
}
bool get_hostHeading(float &heading)
{
	heading = 0;
	if ((get_slam_valid()) && (slamMsg->meta_data.HostHeadingUnc != 0))
	{
		heading = slamMsg->meta_data.HostHeading;
		return true;
	}
	return false;
}
bool get_disp_processed_pc()
{
	return disp_processed_pc;
}
void clear_display_stationary_pc()
{
	stationary_pc.clear();
	stationary_pc.width = 0;
	stationary_pc.points.resize(0);
	stationaty_output.header.stamp = ros::Time::now();
	pcl::toROSMsg(stationary_pc, stationaty_output);
	stationaty_output.header.frame_id = "image_radar";
	stationary_pc.clear();
}
void stationary_pc_shutdown_clear()
{
	stationary_targets_sub.shutdown();
	clear_display_stationary_pc();
}
void pointCloud_data_clear()
{
	cloud_corner.clear();
	cloud_corner.width = 0;
	cloud_corner.points.resize(0);
	pcl::toROSMsg(cloud_corner, output);
	output.header.frame_id = "image_radar";
	output.header.stamp = ros::Time::now();
	corner_radar_pcl_pub.publish(output);
}
void corner_radar_data_clear()
{
	cloud_corner.clear();
	cloud_corner.width = 0;
	cloud_corner.points.resize(0);
	pcl::toROSMsg(cloud_corner, output);
	output.header.frame_id = "image_radar";
	output.header.stamp = ros::Time::now();
	corner_radar_pcl_pub.publish(output);
	cloud_corner.clear();
	if (radar_info_msg.data.size() >= 6)
	{
		radar_info_msg.data[3] = 0;
		corner_radar_info_pub.publish(radar_info_msg);
	}
	if (is_wf_postprocess_enable)
	{
		algo_TagtTrc_Trc_Dat_Num = 0;
		wf_object_display_handler();
	}
	if (is_wf_cluster_disp_enable)
	{
		algo_clusterInfo.clusterNum = 0;
		wf_cluster_display_handler();
	}
}
void wf_cluster_clear()
{
	algo_clusterInfo.clusterNum = 0;
	wf_cluster_display_handler();
}
void wf_adas_curb_clear()
{
	visualization_msgs::MarkerArray delete_markers;
	for (size_t i = 0; i < wf_curb_area.markers.size(); ++i)
	{
		visualization_msgs::Marker delete_marker;
		delete_marker.header.frame_id = "image_radar";
		std::string nameSpace = "wf_radar_" + std::to_string(arg_radar_id);
		delete_marker.ns = nameSpace + "_Curb";
		delete_marker.action = visualization_msgs::Marker::DELETE;
		delete_marker.id = wf_curb_area.markers[i].id;
		delete_markers.markers.push_back(delete_marker);
	}
	wf_curb_area_pub.publish(delete_markers);
	wf_curb_area.markers.clear();
	return;
}
void wf_adas_clear()
{
	visualization_msgs::Marker delete_marker;
	delete_marker.action = visualization_msgs::Marker::DELETE;
	delete_marker.header.frame_id = "image_radar";
	delete_marker.ns = "wf_adas_area";
	if (!is_wf_adas_bsd_enable)
	{
		delete_marker.id = adas_marker_start_id;
		if (!wf_bsd_area.markers.empty())
		{
			wf_bsd_area.markers.push_back(delete_marker);
			wf_bsd_area_pub.publish(wf_bsd_area);
		}
		wf_bsd_area.markers.clear();
	}
	if (!is_wf_adas_lca_enable)
	{
		delete_marker.id = adas_marker_start_id + 1;
		if (!wf_lca_area.markers.empty())
		{
			wf_lca_area.markers.push_back(delete_marker);
			wf_lca_area_pub.publish(wf_lca_area);
		}
		wf_lca_area.markers.clear();
	}
	if (!is_wf_adas_dow_enable)
	{
		delete_marker.id = adas_marker_start_id + 2;
		if (!wf_dow_area.markers.empty())
		{
			wf_dow_area.markers.push_back(delete_marker);
			wf_dow_area_pub.publish(wf_dow_area);
		}
		wf_dow_area.markers.clear();
	}
	if (!is_wf_adas_rcw_enable)
	{
		delete_marker.id = adas_marker_start_id + 3;
		if (!wf_rcw_area.markers.empty())
		{
			wf_rcw_area.markers.push_back(delete_marker);
			wf_rcw_area_pub.publish(wf_rcw_area);
		}
		wf_rcw_area.markers.clear();
	}
	if (!is_wf_adas_rcta_enable)
	{
		delete_marker.id = adas_marker_start_id + 4;
		if (!wf_rcta_area.markers.empty())
		{
			wf_rcta_area.markers.push_back(delete_marker);
			wf_rcta_area_pub.publish(wf_rcta_area);
		}
		wf_rcta_area.markers.clear();
	}
	if (!is_wf_adas_fcta_enable)
	{
		delete_marker.id = adas_marker_start_id + 5;
		if (!wf_fcta_area.markers.empty())
		{
			wf_fcta_area.markers.push_back(delete_marker);
			wf_fcta_area_pub.publish(wf_fcta_area);
		}
		wf_fcta_area.markers.clear();
	}
	return;
}
void rd_data_read_callback(const arbe_msgs::wfTiRDdata::ConstPtr &msg)
{
	if (msg->RDdataB.size() >= 256 * 64)
	{
		for (size_t i = 0; i < 256 * 64; ++i)
		{
			rdData[i] = msg->RDdataB[i];
		}
	}
}
void power_hash_tbl_set_value(float val)
{
	for (uint32_t ind_0 = 0; ind_0 < 512; ind_0++)
	{
		for (uint32_t ind_1 = 0; ind_1 < 2000; ind_1++)
		{
			power_hash_table[ind_0][ind_1] = val;
		}
	}
}
void pc_shutdown_clear()
{
	targets_sub.shutdown();
	targets_legacy_sub.shutdown();
	cloud_corner.clear();
	output.header.stamp = ros::Time::now();
	pcl::toROSMsg(cloud_corner, output);
	output.header.frame_id = "image_radar";
	arbe_pcl_pub.publish(output);
	cloud_corner.clear();
}
void set_pc_sub(bool toShowPC, bool disp_processed_pc_l, int radar_id)
{
	if (toShowPC)
	{
		set_disp_run_once = true;
		ros::NodeHandle n("~");
		n.setCallbackQueue(&pc_disp_queue[IND_FOR_PC_SUB]);
		if (disp_processed_pc_l)
		{
			disp_processed_pc = true;
			is_processed_pc_display_on = true;
		}
		else
		{
			disp_processed_pc = false;
			stationary_pc_shutdown_clear();
			is_processed_pc_display_on = false;
		}
		corner_radar_post_process_data_Sub.shutdown();
		algo_InitFlg = 1;
		corner_radar_post_process_data_Sub = n.subscribe("/wf/corner_radar/lgu_data_" + std::to_string(arg_radar_id), 10, corner_radar_post_process_data_callback);
		is_pc_display_on = true;
	}
	else
	{
		stationary_targets_sub.shutdown();
		targets_sub.shutdown();
		targets_legacy_sub.shutdown();
		corner_radar_post_process_data_Sub.shutdown();
		corner_radar_data_clear();
		is_pc_display_on = false;
		is_processed_pc_display_on = false;
		is_clear_PC_frame_on = true;
	}
}
bool is_disp_processed_pc_changed(bool flag)
{
	return is_processed_pc_display_on != flag;
}
bool is_pc_display_changed(bool displayPC)
{
	return is_pc_display_on != displayPC;
}
void set_disp_pc(bool displayPC, bool disp_processed_pc_l)
{
	if (displayPC)
	{
		if (is_pc_display_changed(displayPC))
		{
			set_pc_sub(displayPC, disp_processed_pc_l, arg_radar_id);
		}
	}
	else
	{
		if (is_pc_display_changed(displayPC))
		{
			set_pc_sub(displayPC, disp_processed_pc_l, arg_radar_id);
		}
	}
}
void wf_pub_obj_vis()
{
	if (wf_object_arrows.markers.size() != 0)
	{
		wf_bbox_arrows_pub.publish(wf_object_arrows);
	}
	if (wf_object_referPt.markers.size() != 0)
	{
		wf_bbox_referPt_pub.publish(wf_object_referPt);
	}
	if (wf_object_boxes.markers.size() != 0)
	{
		wf_bbox_pub.publish(wf_object_boxes);
	}
	if (wf_object_tags.markers.size() != 0)
	{
		wf_bbox_tags_pub.publish(wf_object_tags);
	}
}

void update_raw_sgu_display_cache()
{
	raw_sgu_display_objects.clear();
	if (mAlgoPerOutputPtr == nullptr)
	{
		return;
	}

	const unsigned int sgu_num = std::min<unsigned int>(mAlgoPerOutputPtr->SGUNum, objNumout);
	raw_sgu_display_objects.reserve(sgu_num);
	for (unsigned int i = 0; i < sgu_num; ++i)
	{
		const auto &sgu = mAlgoPerOutputPtr->objTrans[i];
		if ((sgu.objID == 0U) && (std::fabs(sgu.distX / 100.0f) < 0.01f))
		{
			continue;
		}

		RawSguDisplayObject raw_obj;
		raw_obj.obj_id = sgu.objID;
		raw_obj.obj_type = sgu.objType;
		raw_obj.dyn_flag = sgu.dynFlg;
		raw_obj.x = sgu.distX / 100.0f;
		raw_obj.y = sgu.distY / 100.0f;
		raw_obj.yaw = sgu.yawAng / 100.0f;
		raw_obj.length = sgu.length / 100.0f;
		raw_obj.width = sgu.width / 100.0f;
		raw_obj.vel_x = sgu.velX / 100.0f;
		raw_obj.vel_y = sgu.velY / 100.0f;
		raw_obj.vel_abs_x = sgu.velAbsX / 100.0f;
		raw_obj.vel_abs_y = sgu.velAbsY / 100.0f;
		raw_obj.f_ttc = sgu.fTTC / 100.0f;
		raw_obj.f_ddci = sgu.fDDCI / 100.0f;
		raw_sgu_display_objects.push_back(raw_obj);
	}
}

// 原始 SGU 只写入独立的 ObjectList 消息，不写入算法输入或输出结构。
void publish_raw_sgu_object_list()
{
	arbe_msgs::wfObjectMsg raw_object_list = algo_object_list_for_display;
	raw_object_list.header.frame_id = "image_radar";
	raw_object_list.header.stamp = ros::Time::now();

	if (raw_sgu_display_objects.empty())
	{
		if (raw_object_list.ObjectsBuffer.empty())
		{
			arbe_msgs::wfSObj empty_object{};
			empty_object.ID = -1;
			raw_object_list.ObjectsBuffer.push_back(empty_object);
		}
	}
	else
	{
		raw_object_list.ObjectsBuffer.reserve(raw_object_list.ObjectsBuffer.size() + raw_sgu_display_objects.size());
		for (const RawSguDisplayObject &raw_obj : raw_sgu_display_objects)
		{
			arbe_msgs::wfSObj object{};
			object.ID = kRawSguObjectListIdBase + raw_obj.obj_id;
			object.objID = static_cast<uint8_t>(raw_obj.obj_id);
			object.obj_class = raw_obj.obj_type;
			object.position.x = raw_obj.x;
			object.position.y = raw_obj.y;
			object.position.z = 0.0f;
			object.bounding_box.scale_x = raw_obj.length;
			object.bounding_box.scale_y = raw_obj.width;
			object.bounding_box.scale_z = 1.0f;
			object.velocity.x_dot = raw_obj.vel_x;
			object.velocity.y_dot = raw_obj.vel_y;
			object.RxReal = raw_obj.x;
			object.RyReal = raw_obj.y;
			object.RzReal = 0.0f;
			object.Ang = raw_obj.yaw;
			object.Vx = raw_obj.vel_x;
			object.Vy = raw_obj.vel_y;
			object.Vz = 0.0f;
			object.distX = raw_obj.x;
			object.distY = raw_obj.y;
			object.velAbsX = raw_obj.vel_abs_x;
			object.velAbsY = raw_obj.vel_abs_y;
			object.fTTC = raw_obj.f_ttc;
			object.fDDCI = raw_obj.f_ddci;
			raw_object_list.ObjectsBuffer.push_back(object);
		}
	}
	wf_objectlist_pub.publish(raw_object_list);
}

static void publish_deleted_markers(ros::Publisher &publisher, visualization_msgs::MarkerArray &markers)
{
	if (markers.markers.empty())
	{
		return;
	}
	for (visualization_msgs::Marker &marker : markers.markers)
	{
		marker.action = visualization_msgs::Marker::DELETE;
		marker.lifetime = ros::Duration(0.0);
	}
	publisher.publish(markers);
	markers.markers.clear();
}

void clear_wf_algorithm_object_markers()
{
	publish_deleted_markers(wf_bbox_pub, wf_object_boxes);
	publish_deleted_markers(wf_bbox_tags_pub, wf_object_tags);
	publish_deleted_markers(wf_bbox_arrows_pub, wf_object_arrows);
	publish_deleted_markers(wf_bbox_referPt_pub, wf_object_referPt);
	algo_object_list_for_display.ObjectsBuffer.clear();
}

void clear_raw_sgu_object_markers()
{
	publish_deleted_markers(wf_bbox_pub, wf_raw_sgu_object_boxes);
	publish_deleted_markers(wf_bbox_tags_pub, wf_raw_sgu_object_tags);
}

// 原始 SGU 显示始终使用独立 Marker 命名空间和缓存，不会写入 algo_objInfo。
void wf_raw_sgu_object_display_handler()
{
	publish_raw_sgu_object_list();
	if (raw_sgu_display_objects.empty())
	{
		clear_raw_sgu_object_markers();
		return;
	}

	const std::string name_space = "wf_radar_" + std::to_string(arg_radar_id) + "_raw_sgu";
	const ros::Time stamp = ros::Time::now();
	const size_t old_marker_count = wf_raw_sgu_object_boxes.markers.size();
	if (old_marker_count > raw_sgu_display_objects.size())
	{
		visualization_msgs::MarkerArray delete_boxes;
		visualization_msgs::MarkerArray delete_tags;
		for (size_t i = raw_sgu_display_objects.size(); i < old_marker_count; ++i)
		{
			visualization_msgs::Marker deleted_box = wf_raw_sgu_object_boxes.markers[i];
			visualization_msgs::Marker deleted_tag = wf_raw_sgu_object_tags.markers[i];
			deleted_box.action = visualization_msgs::Marker::DELETE;
			deleted_tag.action = visualization_msgs::Marker::DELETE;
			delete_boxes.markers.push_back(deleted_box);
			delete_tags.markers.push_back(deleted_tag);
		}
		wf_bbox_pub.publish(delete_boxes);
		wf_bbox_tags_pub.publish(delete_tags);
	}
	wf_raw_sgu_object_boxes.markers.resize(raw_sgu_display_objects.size());
	wf_raw_sgu_object_tags.markers.resize(raw_sgu_display_objects.size());

	for (size_t i = 0; i < raw_sgu_display_objects.size(); ++i)
	{
		const RawSguDisplayObject &raw_obj = raw_sgu_display_objects[i];
		visualization_msgs::Marker &box = wf_raw_sgu_object_boxes.markers[i];
		box.header.frame_id = "image_radar";
		box.header.stamp = stamp;
		box.ns = name_space + "_object";
		box.id = static_cast<int>(i);
		box.type = visualization_msgs::Marker::CUBE;
		box.action = visualization_msgs::Marker::ADD;
		box.pose.position.x = raw_obj.x;
		box.pose.position.y = raw_obj.y;
		box.pose.position.z = 0.0f;
		tf2::Quaternion rotation;
		rotation.setRPY(0.0, 0.0, raw_obj.yaw * System_D2R);
		rotation.normalize();
		box.pose.orientation.x = rotation.getX();
		box.pose.orientation.y = rotation.getY();
		box.pose.orientation.z = rotation.getZ();
		box.pose.orientation.w = rotation.getW();
		box.scale.x = std::max(0.1f, raw_obj.length);
		box.scale.y = std::max(0.1f, raw_obj.width);
		box.scale.z = 1.0f;
		box.color.r = 0.0f;
		box.color.g = 0.9f;
		box.color.b = 1.0f;
		box.color.a = 0.55f;
		// 原始 SGU 保留最后一帧，播放器暂停或停止时不因 Marker 超时消失。
		box.lifetime = ros::Duration(0.0);

		visualization_msgs::Marker &tag = wf_raw_sgu_object_tags.markers[i];
		tag = box;
		tag.ns = name_space + "_tag";
		tag.type = visualization_msgs::Marker::TEXT_VIEW_FACING;
		tag.pose.position.z = 1.2f;
		tag.pose.orientation.x = 0.0;
		tag.pose.orientation.y = 0.0;
		tag.pose.orientation.z = 0.0;
		tag.pose.orientation.w = 1.0;
		tag.scale.x = 0.0;
		tag.scale.y = 0.0;
		tag.scale.z = 1.0f;
		tag.color.r = 0.0f;
		tag.color.g = 0.9f;
		tag.color.b = 1.0f;
		tag.color.a = 1.0f;
		tag.text = "RAW_SGU:" + std::to_string(raw_obj.obj_id);
	}

	if (!wf_raw_sgu_object_boxes.markers.empty())
	{
		wf_bbox_pub.publish(wf_raw_sgu_object_boxes);
		wf_bbox_tags_pub.publish(wf_raw_sgu_object_tags);
	}
}

void wf_pub_cluster_vis()
{
	if (wf_cluster_boxes.markers.size() != 0)
	{
		wf_cluster_bbox_pub.publish(wf_cluster_boxes);
	}
}
void wf_pub_adas_vis()
{
	if (is_wf_adas_bsd_enable)
	{
		if (wf_bsd_area.markers.size() != 0)
		{
			wf_bsd_area_pub.publish(wf_bsd_area);
		}
	}
	if (is_wf_adas_lca_enable)
	{
		if (wf_lca_area.markers.size() != 0)
		{
			wf_lca_area_pub.publish(wf_lca_area);
		}
	}
	if (is_wf_adas_dow_enable)
	{
		if (wf_dow_area.markers.size() != 0)
		{
			wf_dow_area_pub.publish(wf_dow_area);
		}
	}
	if (is_wf_adas_rcw_enable)
	{
		if (wf_rcw_area.markers.size() != 0)
		{
			wf_rcw_area_pub.publish(wf_rcw_area);
		}
	}
	if (is_wf_adas_rcta_enable)
	{
		if (wf_rcta_area.markers.size() != 0)
		{
			wf_rcta_area_pub.publish(wf_rcta_area);
		}
	}
	if (is_wf_adas_fcta_enable)
	{
		if (wf_fcta_area.markers.size() != 0)
		{
			wf_fcta_area_pub.publish(wf_fcta_area);
		}
	}
}
void wf_pub_curb_vis()
{
	if (is_wf_adas_curb_enable)
	{
		if (wf_curb_area.markers.size() != 0)
		{
			wf_curb_area_pub.publish(wf_curb_area);
		}
	}
}
bool save_obj_json()
{
}
void wf_adas_display_handler()
{
	wf_bsd_area.markers.resize(1);
	wf_lca_area.markers.resize(1);
	wf_rcta_area.markers.resize(1);
	wf_bsd_area.markers[0].points.clear();
	wf_lca_area.markers[0].points.clear();
	wf_rcta_area.markers[0].points.clear();
	wf_dow_area.markers.resize(1);
	wf_rcw_area.markers.resize(1);
	wf_fcta_area.markers.resize(1);
	wf_dow_area.markers[0].points.clear();
	wf_rcw_area.markers[0].points.clear();
	wf_fcta_area.markers[0].points.clear();
	if (arg_radar_id == 1 || arg_radar_id == 3)
	{
		algo_BsdRoiNum = algo_adasRoi.leftBsdRoi.num;
		algo_LcaRoiNum = algo_adasRoi.leftLcaRoi.num;
		algo_RctaRoiNum = algo_adasRoi.leftRctaRoi.num;
		algo_DowRoiNum = algo_adasRoi.leftDowRoi.num;
		algo_RcwRoiNum = algo_adasRoi.rcwRoi.num;
		algo_FctaRoiNum = algo_adasRoi.leftFctaRoi.num;
		algo_BsdRoi = algo_adasRoi.leftBsdRoi;
		algo_LcaRoi = algo_adasRoi.leftLcaRoi;
		algo_RctaRoi = algo_adasRoi.leftRctaRoi;
		algo_DowRoi = algo_adasRoi.leftDowRoi;
		algo_RcwRoi = algo_adasRoi.rcwRoi;
		algo_FctaRoi = algo_adasRoi.leftFctaRoi;
		adas_marker_start_id = 200;
	}
	else if (arg_radar_id == 2 || arg_radar_id == 4)
	{
		algo_BsdRoiNum = algo_adasRoi.rightBsdRoi.num;
		algo_LcaRoiNum = algo_adasRoi.rightLcaRoi.num;
		algo_RctaRoiNum = algo_adasRoi.rightRctaRoi.num;
		algo_DowRoiNum = algo_adasRoi.rightDowRoi.num;
		algo_RcwRoiNum = algo_adasRoi.rcwRoi.num;
		algo_FctaRoiNum = algo_adasRoi.rightFctaRoi.num;
		algo_BsdRoi = algo_adasRoi.rightBsdRoi;
		algo_LcaRoi = algo_adasRoi.rightLcaRoi;
		algo_RctaRoi = algo_adasRoi.rightRctaRoi;
		algo_DowRoi = algo_adasRoi.rightDowRoi;
		algo_RcwRoi = algo_adasRoi.rcwRoi;
		algo_FctaRoi = algo_adasRoi.rightFctaRoi;
		adas_marker_start_id = 800;
	}
	if (algo_BsdRoiNum != 0)
	{
		wf_bsd_area.markers[0].header.frame_id = "image_radar";
		wf_bsd_area.markers[0].header.stamp = ros::Time::now();
		wf_bsd_area.markers[0].ns = "wf_adas_area";
		wf_bsd_area.markers[0].id = adas_marker_start_id;
		wf_bsd_area.markers[0].type = visualization_msgs::Marker::LINE_STRIP;
		wf_bsd_area.markers[0].action = visualization_msgs::Marker::ADD;
		wf_bsd_area.markers[0].scale.x = 0.1;
		wf_bsd_area.markers[0].scale.y = 0.1;
		wf_bsd_area.markers[0].scale.z = 0.1;
		wf_bsd_area.markers[0].color.a = 1.0;
		wf_bsd_area.markers[0].color.r = 1;
		wf_bsd_area.markers[0].color.g = 0;
		wf_bsd_area.markers[0].color.b = 0;
		geometry_msgs::Point p;
		for (uint32_t i = 0; i < algo_BsdRoiNum; i++)
		{
			p.x = algo_BsdRoi.points[i].x;
			p.y = algo_BsdRoi.points[i].y;
			p.z = arg_radar_z_offset;
			wf_bsd_area.markers[0].points.push_back(p);
		}
		p.x = algo_BsdRoi.points[0].x;
		p.y = algo_BsdRoi.points[0].y;
		wf_bsd_area.markers[0].points.push_back(p);
		wf_bsd_area.markers[0].lifetime = ros::Duration(0);
	}
	if (algo_LcaRoiNum != 0)
	{
		wf_lca_area.markers[0].header.frame_id = "image_radar";
		wf_lca_area.markers[0].header.stamp = ros::Time::now();
		wf_lca_area.markers[0].ns = "wf_adas_area";
		wf_lca_area.markers[0].id = adas_marker_start_id + 1;
		wf_lca_area.markers[0].type = visualization_msgs::Marker::LINE_STRIP;
		wf_lca_area.markers[0].action = visualization_msgs::Marker::ADD;
		wf_lca_area.markers[0].color.a = 0.5;
		wf_lca_area.markers[0].color.r = 0.0;
		wf_lca_area.markers[0].color.g = 1.0;
		wf_lca_area.markers[0].color.b = 0.0;
		wf_lca_area.markers[0].scale.x = 0.1;
		wf_lca_area.markers[0].scale.y = 0.1;
		wf_lca_area.markers[0].scale.z = 0.1;
		geometry_msgs::Point p;
		for (uint32_t i = 0; i < algo_LcaRoiNum; i++)
		{
			p.x = algo_LcaRoi.points[i].x;
			p.y = algo_LcaRoi.points[i].y;
			p.z = arg_radar_z_offset;
			wf_lca_area.markers[0].points.push_back(p);
		}
		p.x = algo_LcaRoi.points[0].x;
		p.y = algo_LcaRoi.points[0].y;
		wf_lca_area.markers[0].points.push_back(p);
		wf_lca_area.markers[0].lifetime = ros::Duration(0);
	}
	if (algo_DowRoiNum != 0)
	{
		wf_dow_area.markers[0].header.frame_id = "image_radar";
		wf_dow_area.markers[0].header.stamp = ros::Time::now();
		wf_dow_area.markers[0].ns = "wf_adas_area";
		wf_dow_area.markers[0].id = adas_marker_start_id + 2;
		wf_dow_area.markers[0].type = visualization_msgs::Marker::LINE_STRIP;
		wf_dow_area.markers[0].action = visualization_msgs::Marker::ADD;
		wf_dow_area.markers[0].color.a = 1.0;
		wf_dow_area.markers[0].color.r = 1.0;
		wf_dow_area.markers[0].color.g = 0.0;
		wf_dow_area.markers[0].color.b = 0.0;
		wf_dow_area.markers[0].scale.x = 0.1;
		wf_dow_area.markers[0].scale.y = 0.1;
		wf_dow_area.markers[0].scale.z = 0.1;
		geometry_msgs::Point p;
		for (uint32_t i = 0; i < algo_DowRoiNum; i++)
		{
			p.x = algo_DowRoi.points[i].x;
			p.y = algo_DowRoi.points[i].y;
			p.z = arg_radar_z_offset;
			wf_dow_area.markers[0].points.push_back(p);
		}
		p.x = algo_DowRoi.points[0].x;
		p.y = algo_DowRoi.points[0].y;
		wf_dow_area.markers[0].points.push_back(p);
		wf_dow_area.markers[0].lifetime = ros::Duration(0);
	}
	if (algo_RcwRoiNum != 0)
	{
		wf_rcw_area.markers[0].header.frame_id = "image_radar";
		wf_rcw_area.markers[0].header.stamp = ros::Time::now();
		wf_rcw_area.markers[0].ns = "wf_adas_area";
		wf_rcw_area.markers[0].id = adas_marker_start_id + 3;
		wf_rcw_area.markers[0].type = visualization_msgs::Marker::LINE_STRIP;
		wf_rcw_area.markers[0].action = visualization_msgs::Marker::ADD;
		wf_rcw_area.markers[0].color.a = 1.0;
		wf_rcw_area.markers[0].color.r = 0.0;
		wf_rcw_area.markers[0].color.g = 1.0;
		wf_rcw_area.markers[0].color.b = 0.0;
		wf_rcw_area.markers[0].scale.x = 0.1;
		wf_rcw_area.markers[0].scale.y = 0.1;
		wf_rcw_area.markers[0].scale.z = 0.1;
		geometry_msgs::Point p;
		for (uint32_t i = 0; i < algo_RcwRoiNum; i++)
		{
			p.x = algo_RcwRoi.points[i].x;
			p.y = algo_RcwRoi.points[i].y;
			p.z = arg_radar_z_offset;
			wf_rcw_area.markers[0].points.push_back(p);
		}
		p.x = algo_RcwRoi.points[0].x;
		p.y = algo_RcwRoi.points[0].y;
		wf_rcw_area.markers[0].points.push_back(p);
		wf_rcw_area.markers[0].lifetime = ros::Duration(0);
	}
	if (algo_RctaRoiNum != 0)
	{
		wf_rcta_area.markers[0].header.frame_id = "image_radar";
		wf_rcta_area.markers[0].header.stamp = ros::Time::now();
		wf_rcta_area.markers[0].ns = "wf_adas_area";
		wf_rcta_area.markers[0].id = adas_marker_start_id + 4;
		wf_rcta_area.markers[0].type = visualization_msgs::Marker::LINE_STRIP;
		wf_rcta_area.markers[0].action = visualization_msgs::Marker::ADD;
		wf_rcta_area.markers[0].color.a = 1.0;
		wf_rcta_area.markers[0].color.r = 0.0;
		wf_rcta_area.markers[0].color.g = 0.0;
		wf_rcta_area.markers[0].color.b = 1;
		wf_rcta_area.markers[0].scale.x = 0.1;
		wf_rcta_area.markers[0].scale.y = 0.1;
		wf_rcta_area.markers[0].scale.z = 0.1;
		geometry_msgs::Point p;
		for (uint32_t i = 0; i < algo_RctaRoiNum; i++)
		{
			p.x = algo_RctaRoi.points[i].x;
			p.y = algo_RctaRoi.points[i].y;
			p.z = arg_radar_z_offset;
			wf_rcta_area.markers[0].points.push_back(p);
		}
		p.x = algo_RctaRoi.points[0].x;
		p.y = algo_RctaRoi.points[0].y;
		wf_rcta_area.markers[0].points.push_back(p);
		wf_rcta_area.markers[0].lifetime = ros::Duration(0);
	}
	if (algo_FctaRoiNum != 0)
	{
		wf_fcta_area.markers[0].header.frame_id = "image_radar";
		wf_fcta_area.markers[0].header.stamp = ros::Time::now();
		wf_fcta_area.markers[0].ns = "wf_adas_area";
		wf_fcta_area.markers[0].id = adas_marker_start_id + 5;
		wf_fcta_area.markers[0].type = visualization_msgs::Marker::LINE_STRIP;
		wf_fcta_area.markers[0].action = visualization_msgs::Marker::ADD;
		wf_fcta_area.markers[0].color.a = 1.0;
		wf_fcta_area.markers[0].color.r = 1.0;
		wf_fcta_area.markers[0].color.g = 1.0;
		wf_fcta_area.markers[0].color.b = 1.0;
		wf_fcta_area.markers[0].scale.x = 0.1;
		wf_fcta_area.markers[0].scale.y = 0.1;
		wf_fcta_area.markers[0].scale.z = 0.1;
		geometry_msgs::Point p;
		for (uint32_t i = 0; i < algo_FctaRoiNum; i++)
		{
			p.x = algo_FctaRoi.points[i].x;
			p.y = algo_FctaRoi.points[i].y;
			p.z = arg_radar_z_offset;
			wf_fcta_area.markers[0].points.push_back(p);
		}
		p.x = algo_FctaRoi.points[0].x;
		p.y = algo_FctaRoi.points[0].y;
		wf_fcta_area.markers[0].points.push_back(p);
		wf_fcta_area.markers[0].lifetime = ros::Duration(0);
	}
	wf_pub_adas_vis();
}
void wf_curb_display_handler()
{
	uint32_t ploted_num = 0;
	wf_curb_area.markers.clear();
	std::string nameSpace = "wf_radar_" + std::to_string(arg_radar_id);
	int mainLeftCurbNum = algo_curbDBSCAN.mainLeftCurbNum;
	int mainRightCurbNum = algo_curbDBSCAN.mainRightCurbNum;
	int commonCredVerCurbNum = algo_curbDBSCAN.commonCredVerCurbNum;
	int credHozCurb = algo_curbDBSCAN.credHozCurb;
	curbDBSCANOutput curbDBSCAN = algo_curbDBSCAN;
	CurbPlotStruct mainLeftCurb4plot = algo_curbDBSCAN.mainLeftCurb4plot;
	CurbPlotStruct mainRightCurb4plot = algo_curbDBSCAN.mainRightCurb4plot;
	CurbPlotStruct *commonCredVerCurb4plot = algo_curbDBSCAN.commonCredVerCurb4plot;
	CurbPlotStruct *commonCredHozCurb4plot = algo_curbDBSCAN.commonCredHozCurb4plot;
	if (mainLeftCurbNum > 0)
	{
		visualization_msgs::Marker mainLeftCurb_marker;
		mainLeftCurb_marker.header.frame_id = "image_radar";
		mainLeftCurb_marker.header.stamp = ros::Time::now();
		mainLeftCurb_marker.ns = nameSpace + "_Curb";
		mainLeftCurb_marker.id = ploted_num;
		mainLeftCurb_marker.type = visualization_msgs::Marker::LINE_STRIP;
		mainLeftCurb_marker.action = visualization_msgs::Marker::ADD;
		mainLeftCurb_marker.scale.x = 1;
		mainLeftCurb_marker.scale.y = 1;
		mainLeftCurb_marker.scale.z = 0.1;
		mainLeftCurb_marker.color.a = 0.7;
		mainLeftCurb_marker.color.r = 1.0;
		mainLeftCurb_marker.color.g = 0.0;
		mainLeftCurb_marker.color.b = 0.0;
		if (mainLeftCurb4plot.isCurve == 0)
		{
			for (int i = 0; i < 2; i++)
			{
				geometry_msgs::Point p;
				p.x = mainLeftCurb4plot.points[i].x + arg_radar_x_offset;
				p.y = mainLeftCurb4plot.points[i].y + arg_radar_y_offset;
				p.z = arg_radar_z_offset;
				mainLeftCurb_marker.points.push_back(p);
			}
		}
		else
		{
			int pointNums = 0;
			if (algo_RadarPos.m_mountingPosition.radar_pos <= RadarPos_FrontRight)
			{
				pointNums = floor(curbDBSCAN.curbVer[curbDBSCAN.mainLeftCurbIDIndex].maxX) - floor(curbDBSCAN.curbVer[curbDBSCAN.mainLeftCurbIDIndex].minX) + 1;
			}
			else
			{
				pointNums = floor(curbDBSCAN.curbVer[curbDBSCAN.mainRightCurbIDIndex].maxX) - floor(curbDBSCAN.curbVer[curbDBSCAN.mainRightCurbIDIndex].minX) + 1;
			}
			for (int Xoffset = 0; Xoffset < pointNums; Xoffset++)
			{
				geometry_msgs::Point p;
				if (algo_RadarPos.m_mountingPosition.radar_pos <= RadarPos_FrontRight)
				{
					p.x = mainLeftCurb4plot.points[0].x + Xoffset;
					p.y = pow(p.x, 3) * mainLeftCurb4plot.A3 + pow(p.x, 2) * mainLeftCurb4plot.A2 + p.x * mainLeftCurb4plot.A1 + mainLeftCurb4plot.A0;
					p.x = p.x + arg_radar_x_offset;
					p.y = p.y + arg_radar_y_offset;
				}
				else
				{
					p.x = -mainLeftCurb4plot.points[0].x + Xoffset;
					p.y = pow(p.x, 3) * mainLeftCurb4plot.A3 + pow(p.x, 2) * mainLeftCurb4plot.A2 + p.x * mainLeftCurb4plot.A1 + mainLeftCurb4plot.A0;
					p.x = -p.x + arg_radar_x_offset;
					p.y = -p.y + arg_radar_y_offset;
				}
				p.z = arg_radar_z_offset;
				mainLeftCurb_marker.points.push_back(p);
			}
		}
		wf_curb_area.markers.push_back(mainLeftCurb_marker);
		ploted_num++;
	}
	if (mainRightCurbNum > 0)
	{
		visualization_msgs::Marker mainRightCurb_marker;
		mainRightCurb_marker.header.frame_id = "image_radar";
		mainRightCurb_marker.header.stamp = ros::Time::now();
		mainRightCurb_marker.ns = nameSpace + "_Curb";
		mainRightCurb_marker.id = ploted_num;
		mainRightCurb_marker.type = visualization_msgs::Marker::LINE_STRIP;
		mainRightCurb_marker.action = visualization_msgs::Marker::ADD;
		mainRightCurb_marker.scale.x = 1;
		mainRightCurb_marker.scale.y = 1;
		mainRightCurb_marker.scale.z = 0.1;
		mainRightCurb_marker.color.a = 0.7;
		mainRightCurb_marker.color.r = 1.0;
		mainRightCurb_marker.color.g = 0.5;
		mainRightCurb_marker.color.b = 0.0;
		if (mainRightCurb4plot.isCurve == 0)
		{
			for (int i = 0; i < 2; i++)
			{
				geometry_msgs::Point p;
				p.x = mainRightCurb4plot.points[i].x + arg_radar_x_offset;
				p.y = mainRightCurb4plot.points[i].y + arg_radar_y_offset;
				p.z = arg_radar_z_offset;
				mainRightCurb_marker.points.push_back(p);
			}
		}
		else
		{
			int pointNums = 0;
			if (algo_RadarPos.m_mountingPosition.radar_pos <= RadarPos_FrontRight)
			{
				pointNums = floor(curbDBSCAN.curbVer[curbDBSCAN.mainRightCurbIDIndex].maxX) - floor(curbDBSCAN.curbVer[curbDBSCAN.mainRightCurbIDIndex].minX) + 1;
			}
			else
			{
				pointNums = floor(curbDBSCAN.curbVer[curbDBSCAN.mainLeftCurbIDIndex].maxX) - floor(curbDBSCAN.curbVer[curbDBSCAN.mainLeftCurbIDIndex].minX) + 1;
			}
			for (int Xoffset = 0; Xoffset < pointNums; Xoffset++)
			{
				geometry_msgs::Point p;
				if (algo_RadarPos.m_mountingPosition.radar_pos <= RadarPos_FrontRight)
				{
					p.x = mainRightCurb4plot.points[0].x + Xoffset;
					p.y = pow(p.x, 3) * mainRightCurb4plot.A3 + pow(p.x, 2) * mainRightCurb4plot.A2 + p.x * mainRightCurb4plot.A1 + mainRightCurb4plot.A0;
					p.x = p.x + arg_radar_x_offset;
					p.y = p.y + arg_radar_y_offset;
				}
				else
				{
					p.x = -mainRightCurb4plot.points[0].x + Xoffset;
					p.y = pow(p.x, 3) * mainRightCurb4plot.A3 + pow(p.x, 2) * mainRightCurb4plot.A2 + p.x * mainRightCurb4plot.A1 + mainRightCurb4plot.A0;
					p.x = -p.x + arg_radar_x_offset;
					p.y = -p.y + arg_radar_y_offset;
				}
				p.z = arg_radar_z_offset;
				mainRightCurb_marker.points.push_back(p);
			}
		}
		wf_curb_area.markers.push_back(mainRightCurb_marker);
		ploted_num++;
	}
	if (commonCredVerCurbNum > 0)
	{
		for (int j = 0; j < commonCredVerCurbNum; j++)
		{
			visualization_msgs::Marker commonCredVerCurb_marker;
			commonCredVerCurb_marker.header.frame_id = "image_radar";
			commonCredVerCurb_marker.header.stamp = ros::Time::now();
			commonCredVerCurb_marker.ns = nameSpace + "_Curb";
			commonCredVerCurb_marker.id = ploted_num;
			commonCredVerCurb_marker.type = visualization_msgs::Marker::LINE_STRIP;
			commonCredVerCurb_marker.action = visualization_msgs::Marker::ADD;
			commonCredVerCurb_marker.color.a = 0.5;
			commonCredVerCurb_marker.color.r = 0.0;
			commonCredVerCurb_marker.color.g = 1.0;
			commonCredVerCurb_marker.color.b = 0.0;
			commonCredVerCurb_marker.scale.x = 1;
			commonCredVerCurb_marker.scale.y = 1;
			commonCredVerCurb_marker.scale.z = 0.1;
			if (commonCredVerCurb4plot[j].isCurve == 0)
			{
				for (uint32_t i = 0; i < 2; i++)
				{
					geometry_msgs::Point p;
					p.x = commonCredVerCurb4plot[j].points[i].x + arg_radar_x_offset;
					p.y = commonCredVerCurb4plot[j].points[i].y + arg_radar_y_offset;
					p.z = arg_radar_z_offset;
					commonCredVerCurb_marker.points.push_back(p);
				}
			}
			else
			{
				int pointNums = 0;
				if (algo_RadarPos.m_mountingPosition.radar_pos <= RadarPos_FrontRight)
				{
					pointNums = floor(commonCredVerCurb4plot[j].points[1].x) - floor(commonCredVerCurb4plot[j].points[0].x) + 1;
				}
				else
				{
					pointNums = floor(commonCredVerCurb4plot[j].points[0].x) - floor(commonCredVerCurb4plot[j].points[1].x) + 1;
				}
				for (int Xoffset = 0; Xoffset < pointNums; Xoffset++)
				{
					geometry_msgs::Point p;
					if (algo_RadarPos.m_mountingPosition.radar_pos <= RadarPos_FrontRight)
					{
						p.x = commonCredVerCurb4plot[j].points[0].x + Xoffset;
						p.y = pow(p.x, 3) * commonCredVerCurb4plot[j].A3 + pow(p.x, 2) * commonCredVerCurb4plot[j].A2 + p.x * commonCredVerCurb4plot[j].A1 + commonCredVerCurb4plot[j].A0;
						p.x = p.x + arg_radar_x_offset;
						p.y = p.y + arg_radar_y_offset;
					}
					else
					{
						p.x = -commonCredVerCurb4plot[j].points[0].x + Xoffset;
						p.y = pow(p.x, 3) * commonCredVerCurb4plot[j].A3 + pow(p.x, 2) * commonCredVerCurb4plot[j].A2 + p.x * commonCredVerCurb4plot[j].A1 + commonCredVerCurb4plot[j].A0;
						p.x = -p.x + arg_radar_x_offset;
						p.y = -p.y + arg_radar_y_offset;
					}
					p.z = arg_radar_z_offset;
					commonCredVerCurb_marker.points.push_back(p);
				}
			}
			wf_curb_area.markers.push_back(commonCredVerCurb_marker);
			ploted_num++;
		}
	}
	if (credHozCurb > 0)
	{
		for (int j = 0; j < credHozCurb; j++)
		{
			visualization_msgs::Marker credHozCurb_marker;
			credHozCurb_marker.header.frame_id = "image_radar";
			credHozCurb_marker.header.stamp = ros::Time::now();
			credHozCurb_marker.ns = nameSpace + "_Curb";
			credHozCurb_marker.id = ploted_num;
			credHozCurb_marker.type = visualization_msgs::Marker::LINE_STRIP;
			credHozCurb_marker.action = visualization_msgs::Marker::ADD;
			credHozCurb_marker.color.a = 0.5;
			credHozCurb_marker.color.r = 0.0;
			credHozCurb_marker.color.g = 0.0;
			credHozCurb_marker.color.b = 1.0;
			credHozCurb_marker.scale.x = 1;
			credHozCurb_marker.scale.y = 1;
			credHozCurb_marker.scale.z = 0.1;
			for (uint32_t i = 0; i < 2; i++)
			{
				geometry_msgs::Point p;
				p.x = commonCredHozCurb4plot[j].points[i].x + arg_radar_x_offset;
				p.y = commonCredHozCurb4plot[j].points[i].y + arg_radar_y_offset;
				p.z = arg_radar_z_offset;
				credHozCurb_marker.points.push_back(p);
			}
			wf_curb_area.markers.push_back(credHozCurb_marker);
			ploted_num++;
		}
	}
	for (uint32_t i = ploted_num; i < curbMaxNum; i++)
	{
		visualization_msgs::Marker cleanCurb_marker;
		cleanCurb_marker.header.frame_id = "image_radar";
		cleanCurb_marker.header.stamp = ros::Time::now();
		cleanCurb_marker.ns = nameSpace + "_Curb";
		cleanCurb_marker.id = i;
		cleanCurb_marker.type = visualization_msgs::Marker::LINE_STRIP;
		cleanCurb_marker.action = visualization_msgs::Marker::DELETE;
		wf_curb_area.markers.push_back(cleanCurb_marker);
	}
	wf_pub_curb_vis();
}
void wf_object_display_handler()
{
	std::string nameSpace = "wf_radar_" + std::to_string(arg_radar_id);
	if (algo_TagtTrc_Trc_Dat_Num == 0)
	{
		if (wf_object_boxes.markers.size() != 0)
		{
			wf_object_boxes.markers.resize(0);
		}
		if (wf_object_tags.markers.size() != 0)
		{
			wf_object_tags.markers.resize(0);
		}
		if (wf_object_arrows.markers.size() != 0)
		{
			wf_object_arrows.markers.resize(0);
		}
		if (wf_object_referPt.markers.size() != 0)
		{
			wf_object_referPt.markers.resize(0);
		}
		if (wf_object_roadmaps_line.markers.size() != 0)
		{
			wf_object_roadmaps_line.markers.resize(0);
		}
		if (wf_object_roadmaps_point.markers.size() != 0)
		{
			wf_object_roadmaps_point.markers.resize(0);
		}
		if (wf_object_roadmapsFit_line.markers.size() != 0)
		{
			wf_object_roadmapsFit_line.markers.resize(0);
		}
		if (wf_object_roadmapsFit_point.markers.size() != 0)
		{
			wf_object_roadmapsFit_point.markers.resize(0);
		}
	}
	uint32_t shape = visualization_msgs::Marker::CUBE;
	uint32_t arrow_shape = visualization_msgs::Marker::ARROW;
	tf2::Quaternion q_rot;
	wf_object_boxes.markers.resize(algo_TagtTrc_Trc_Dat_Num);
	wf_object_referPt.markers.resize(algo_TagtTrc_Trc_Dat_Num);
	wf_object_arrows.markers.resize(algo_TagtTrc_Trc_Dat_Num);
	wf_object_roadmaps_line.markers.resize(algo_TagtTrc_Trc_Dat_Num);
	wf_object_roadmaps_point.markers.resize(algo_TagtTrc_Trc_Dat_Num);
	wf_object_roadmapsFit_line.markers.resize(algo_TagtTrc_Trc_Dat_Num);
	wf_object_roadmapsFit_point.markers.resize(algo_TagtTrc_Trc_Dat_Num);
	wf_object_tags.markers.resize(algo_TagtTrc_Trc_Dat_Num);
	ObjectListMsg_global.ObjectsBuffer.resize(algo_TagtTrc_Trc_Dat_Num);
	uint32_t marker_i = 0;
	float scale_text = 2;
	bool wf_referPt_enabled_TYadd = false;
	bool wf_box_RotFlg = true;
	bool wf_yaw_angFlg = true;
	bool wf_lost_enabled = false;
	bool is_stopped_dynamic_Flg = true;
	for (uint32_t i = 0; i < algo_TagtTrc_Trc_Dat_Num; i++)
	{
		if (!is_radar_dynamic_obj_enable)
		{
			if (is_stopped_dynamic_Flg)
			{
				if (algo_objInfo.trcOutData[i].dynFlg != 0)
				{
					continue;
				}
			}
			else
			{
				if ((algo_objInfo.trcOutData[i].dynFlg != 0) && (algo_objInfo.trcOutData[i].dynFlg != 4))
				{
					continue;
				}
			}
		}
		if (!is_radar_static_obj_enable)
		{
			if (is_stopped_dynamic_Flg)
			{
				if (algo_objInfo.trcOutData[i].dynFlg == 0)
					continue;
			}
			else
			{
				if ((algo_objInfo.trcOutData[i].dynFlg == 0) || (algo_objInfo.trcOutData[i].dynFlg == 4))
				{
					continue;
				}
			}
		}
		q_rot.setRPY(0, 0, algo_objInfo.trcOutData[i].yawAng * System_D2R);
		q_rot = q_rot.normalize();
		arbe_msgs::wfSObj tar;
		tar.position.x = algo_objInfo.trcOutData[i].distX;
		tar.position.y = algo_objInfo.trcOutData[i].distY;
		tar.position.z = algo_objInfo.trcOutData[i].distZ;
		tar.bounding_box.scale_x = algo_objInfo.trcOutData[i].length;
		tar.bounding_box.scale_y = algo_objInfo.trcOutData[i].width;
		tar.bounding_box.scale_z = algo_objInfo.trcOutData[i].height;
		tar.rcs = algo_objInfo.trcOutData[i].RCS;
		tar.velocity.x_dot = algo_objInfo.trcOutData[i].velX;
		tar.velocity.y_dot = algo_objInfo.trcOutData[i].velY;
		tar.ID = algo_objInfo.trcOutData[i].objUnqID;
		tar.RxReal = algo_objInfo.trcOutData[i].distX;
		tar.RyReal = algo_objInfo.trcOutData[i].distY;
		tar.RzReal = algo_objInfo.trcOutData[i].distZ;
		tar.Ang = algo_objInfo.trcOutData[i].yawAng;
		tar.Vx = algo_objInfo.trcOutData[i].velX;
		tar.Vy = algo_objInfo.trcOutData[i].velY;
		tar.Vz = 0;
		tar.power = 0;
		tar.objID = algo_objInfo.trcOutData[i].objID;
		tar.distX = algo_objInfo.trcOutData[i].distX;
		tar.distY = algo_objInfo.trcOutData[i].distY;
		tar.velAbsX = algo_objInfo.trcOutData[i].velAbsX;
		tar.velAbsY = algo_objInfo.trcOutData[i].velAbsY;
		tar.fTTC = algo_objInfo.trcOutData[i].fTTC;
		tar.fDDCI = algo_objInfo.trcOutData[i].fDDCI;
		tar.objBsdWarningFlag = algo_objInfo.trcOutData[i].objBsdWarningFlag;
		tar.objLcaWarningFlag = algo_objInfo.trcOutData[i].objLcaWarningFlag;
		tar.objDowWarningFlag = algo_objInfo.trcOutData[i].objDowWarningFlag;
		tar.objRcwWarningFlag = algo_objInfo.trcOutData[i].objRcwWarningFlag;
		tar.objRctaWarningFlag = algo_objInfo.trcOutData[i].objRctaWarningFlag;
		tar.objRctbWarningFlag = algo_objInfo.trcOutData[i].objRctbWarningFlag;
		tar.objFctaWarningFlag = algo_objInfo.trcOutData[i].objFctaWarningFlag;
		tar.objFctbWarningFlag = algo_objInfo.trcOutData[i].objFctbWarningFlag;
		ObjectListMsg_global.ObjectsBuffer[i] = tar;
		wf_object_boxes.markers[marker_i].header.frame_id = "image_radar";
		wf_object_boxes.markers[marker_i].header.stamp = ros::Time::now();
		wf_object_boxes.markers[marker_i].ns = nameSpace + "_object";
		wf_object_boxes.markers[marker_i].id = i;
		wf_object_boxes.markers[marker_i].type = visualization_msgs::Marker::CUBE;
		wf_object_boxes.markers[marker_i].action = visualization_msgs::Marker::ADD;
		wf_object_boxes.markers[marker_i].pose.position.x = algo_objInfo.trcOutData[i].distX;
		wf_object_boxes.markers[marker_i].pose.position.y = algo_objInfo.trcOutData[i].distY;
		wf_object_boxes.markers[marker_i].pose.position.z = algo_objInfo.trcOutData[i].distZ;
		wf_object_boxes.markers[marker_i].color.a = 0.7;
		if ((is_dynamic_obj_class_enable) && (algo_objInfo.trcOutData[i].dynFlg != 0))
		{
			wf_object_boxes.markers[marker_i].type = visualization_msgs::Marker::MESH_RESOURCE;
			wf_object_boxes.markers[marker_i].color.a = 1;
			if (algo_objInfo.trcOutData[i].objType == 1)
			{
				wf_object_boxes.markers[marker_i].mesh_resource = "package://arbe_phoenix_radar_driver/src/arbe_visualization_engine/pedestrian.dae";
			}
			else if (algo_objInfo.trcOutData[i].objType == 4)
			{
				wf_object_boxes.markers[marker_i].mesh_resource = "package://arbe_phoenix_radar_driver/src/arbe_visualization_engine/Car.dae";
			}
			else if (algo_objInfo.trcOutData[i].objType == 5)
			{
				wf_object_boxes.markers[marker_i].mesh_resource = "package://arbe_phoenix_radar_driver/src/arbe_visualization_engine/truck.dae";
			}
			else if ((algo_objInfo.trcOutData[i].objType == 2) || (algo_objInfo.trcOutData[i].objType == 3))
			{
				wf_object_boxes.markers[marker_i].mesh_resource = "package://arbe_phoenix_radar_driver/src/arbe_visualization_engine/wheeler.dae";
			}
			else
			{
				wf_object_boxes.markers[marker_i].type = visualization_msgs::Marker::CUBE;
			}
		}
		if (algo_objInfo.trcOutData[i].dynFlg >= 1 && algo_objInfo.trcOutData[i].dynFlg <= 4)
		{
			if (wf_box_RotFlg == false)
			{
				wf_object_boxes.markers[marker_i].pose.orientation.x = 0;
				wf_object_boxes.markers[marker_i].pose.orientation.y = 0;
				wf_object_boxes.markers[marker_i].pose.orientation.z = 0;
				wf_object_boxes.markers[marker_i].pose.orientation.w = 0;
			}
			else
			{
				wf_object_boxes.markers[marker_i].pose.orientation.x = q_rot.getX();
				wf_object_boxes.markers[marker_i].pose.orientation.y = q_rot.getY();
				wf_object_boxes.markers[marker_i].pose.orientation.z = q_rot.getZ();
				wf_object_boxes.markers[marker_i].pose.orientation.w = q_rot.getW();
			}
		}
		else
		{
			wf_object_boxes.markers[marker_i].pose.orientation.x = 0;
			wf_object_boxes.markers[marker_i].pose.orientation.y = 0;
			wf_object_boxes.markers[marker_i].pose.orientation.z = 0;
			wf_object_boxes.markers[marker_i].pose.orientation.w = 0;
		}
		wf_object_boxes.markers[marker_i].pose.position.x = algo_objInfo.trcOutData[i].distX;
		wf_object_boxes.markers[marker_i].pose.position.y = algo_objInfo.trcOutData[i].distY;
		wf_object_boxes.markers[marker_i].pose.position.z = algo_objInfo.trcOutData[i].distZ;
		wf_object_boxes.markers[marker_i].scale.x = algo_objInfo.trcOutData[i].length;
		wf_object_boxes.markers[marker_i].scale.y = algo_objInfo.trcOutData[i].width;
		wf_object_boxes.markers[marker_i].scale.z = algo_objInfo.trcOutData[i].height;
		if ((is_dynamic_obj_class_enable) && (algo_objInfo.trcOutData[i].dynFlg != 0))
		{
			if (algo_objInfo.trcOutData[i].objType == 1)
			{
			}
			else if (algo_objInfo.trcOutData[i].objType == 4)
			{
				wf_object_boxes.markers[marker_i].scale.x = algo_objInfo.trcOutData[i].length / 4;
				wf_object_boxes.markers[marker_i].scale.y = algo_objInfo.trcOutData[i].width / 1.5;
				wf_object_boxes.markers[marker_i].scale.z = algo_objInfo.trcOutData[i].height;
			}
			else if (algo_objInfo.trcOutData[i].objType == 5)
			{
				wf_object_boxes.markers[marker_i].scale.x = algo_objInfo.trcOutData[i].length / 15;
				wf_object_boxes.markers[marker_i].scale.y = algo_objInfo.trcOutData[i].width / 2;
				wf_object_boxes.markers[marker_i].scale.z = algo_objInfo.trcOutData[i].height / 2.5;
			}
			else if ((algo_objInfo.trcOutData[i].objType == 2) || (algo_objInfo.trcOutData[i].objType == 3))
			{
			}
			else
			{
			}
		}
		int red, green, blue;
		if (algo_objInfo.trcOutData[i].dynFlg == 1)
		{
			if ((arg_radar_id == 1) || (arg_radar_id == 3))
			{
				red = 163;
				green = 50;
				blue = 204;
			}
			else
			{
				red = 128;
				green = 0;
				blue = 128;
			}
		}
		else if (algo_objInfo.trcOutData[i].dynFlg == 2)
		{
			if ((arg_radar_id == 1) || (arg_radar_id == 3))
			{
				red = 144;
				green = 238;
				blue = 144;
			}
			else
			{
				red = 0;
				green = 128;
				blue = 0;
			}
		}
		else if (algo_objInfo.trcOutData[i].dynFlg == 3)
		{
			red = 200;
			green = 125;
			blue = 125;
		}
		else if (algo_objInfo.trcOutData[i].dynFlg == 0)
		{
			if (is_static_obj_class_enable)
			{
				if (algo_objInfo.trcOutData[i].objType == 7)
				{
					red = 78;
					green = 131;
					blue = 253;
				}
				else if (algo_objInfo.trcOutData[i].objType == 8)
				{
					red = 255;
					green = 165;
					blue = 0;
					wf_object_boxes.markers[marker_i].type = visualization_msgs::Marker::CYLINDER;
					wf_object_boxes.markers[marker_i].scale.z = 0.5;
				}
				else if (algo_objInfo.trcOutData[i].objType == 6)
				{
					red = 122;
					green = 138;
					blue = 154;
				}
				else
				{
					red = 112;
					green = 128;
					blue = 144;
				}
			}
			else
			{
				red = 112;
				green = 128;
				blue = 144;
			}
		}
		else if (algo_objInfo.trcOutData[i].dynFlg == 4)
		{
			red = 105;
			green = 105;
			blue = 105;
		}
		else
		{
			red = 112;
			green = 128;
			blue = 144;
		}
		if ((is_wf_adas_tgu_enable) && (algo_objInfo.trcOutData[i].TGUValid > 0))
		{
			red = 0;
			green = 255;
			blue = 255;
		}
		if (algo_objInfo.trcOutData[i].existProb < 0.7 && (algo_objInfo.trcOutData[i].dynFlg >= 1 && algo_objInfo.trcOutData[i].dynFlg <= 3))
		{
			wf_object_boxes.markers[marker_i].color.r = 210;
			wf_object_boxes.markers[marker_i].color.g = 180;
			wf_object_boxes.markers[marker_i].color.b = 140;
			wf_object_boxes.markers[marker_i].color.a = 0.6;
		}
		if ((is_wf_adas_enable) && (algo_objInfo.trcOutData[i].objBsdWarningFlag >= emWarningFlag::WarningFlag_Warning ||
									algo_objInfo.trcOutData[i].objLcaWarningFlag >= emWarningFlag::WarningFlag_Warning ||
									algo_objInfo.trcOutData[i].objDowWarningFlag >= emWarningFlag::WarningFlag_Warning ||
									algo_objInfo.trcOutData[i].objRcwWarningFlag >= emWarningFlag::WarningFlag_Warning ||
									algo_objInfo.trcOutData[i].objRctbWarningFlag >= emWarningFlag::WarningFlag_Warning ||
									algo_objInfo.trcOutData[i].objRctaWarningFlag >= emWarningFlag::WarningFlag_Warning ||
									algo_objInfo.trcOutData[i].objFctaWarningFlag >= emWarningFlag::WarningFlag_Warning ||
									algo_objInfo.trcOutData[i].objFctbWarningFlag >= emWarningFlag::WarningFlag_Warning))
		{
			wf_object_boxes.markers[marker_i].color.r = 1.0;
			wf_object_boxes.markers[marker_i].color.g = 0.0;
			wf_object_boxes.markers[marker_i].color.b = 0.0;
		}
		else
		{
			wf_object_boxes.markers[marker_i].color.r = red / 255.0;
			wf_object_boxes.markers[marker_i].color.g = green / 255.0;
			wf_object_boxes.markers[marker_i].color.b = blue / 255.0;
		}
		wf_object_boxes.markers[marker_i].lifetime = ros::Duration(0.05);
		std::string id_text = std::to_string(algo_objInfo.trcOutData[i].objUnqID);
		wf_object_boxes.markers[marker_i].text = id_text;
		if (algo_algoExtraInfo.bUseSizeByClassEnable && wf_referPt_enabled_TYadd)
		{
			wf_object_referPt.markers[marker_i].header.frame_id = "image_radar";
			wf_object_referPt.markers[marker_i].header.stamp = ros::Time::now();
			wf_object_referPt.markers[marker_i].ns = nameSpace + "_object_referPt";
			wf_object_referPt.markers[marker_i].id = i;
			wf_object_referPt.markers[marker_i].lifetime = ros::Duration(0.05);
			if (algo_objInfo.trcOutData[i].dynFlg >= 1 && algo_objInfo.trcOutData[i].dynFlg <= 3)
			{
				wf_object_referPt.markers[marker_i].type = visualization_msgs::Marker::ARROW;
				wf_object_referPt.markers[marker_i].action = visualization_msgs::Marker::ADD;
				wf_object_referPt.markers[marker_i].pose.position.x = algo_objInfo.trcOutData[i].distXRefer;
				wf_object_referPt.markers[marker_i].pose.position.y = algo_objInfo.trcOutData[i].distYRefer;
				wf_object_referPt.markers[marker_i].pose.position.z = algo_objInfo.trcOutData[i].distZ;
				wf_object_referPt.markers[marker_i].pose.orientation.x = 0;
				wf_object_referPt.markers[marker_i].pose.orientation.y = 0;
				wf_object_referPt.markers[marker_i].pose.orientation.z = 0;
				wf_object_referPt.markers[marker_i].pose.orientation.w = 1;
				wf_object_referPt.markers[marker_i].scale.x = 1;
				wf_object_referPt.markers[marker_i].scale.y = 1;
				wf_object_referPt.markers[marker_i].scale.z = 1;
				wf_object_referPt.markers[marker_i].color.r = 1.0;
				wf_object_referPt.markers[marker_i].color.g = 0.0;
				wf_object_referPt.markers[marker_i].color.b = 0.0;
				wf_object_referPt.markers[marker_i].color.a = 0.5;
			}
			else
			{
				wf_object_referPt.markers[marker_i].type = visualization_msgs::Marker::ARROW;
				wf_object_referPt.markers[marker_i].action = visualization_msgs::Marker::DELETE;
			}
		}
		wf_object_arrows.markers[marker_i].header.frame_id = "image_radar";
		wf_object_arrows.markers[marker_i].header.stamp = ros::Time::now();
		wf_object_arrows.markers[marker_i].ns = nameSpace + "_arrow";
		wf_object_arrows.markers[marker_i].id = i;
		wf_object_arrows.markers[marker_i].lifetime = ros::Duration(0.05);
		if (is_wf_object_arrow_enable)
		{
			if (algo_objInfo.trcOutData[i].dynFlg >= 1 && algo_objInfo.trcOutData[i].dynFlg <= 3)
			{
				wf_object_arrows.markers[marker_i].type = visualization_msgs::Marker::ARROW;
				wf_object_arrows.markers[marker_i].action = visualization_msgs::Marker::ADD;
				wf_object_arrows.markers[marker_i].pose.position.x = algo_objInfo.trcOutData[i].distX;
				wf_object_arrows.markers[marker_i].pose.position.y = algo_objInfo.trcOutData[i].distY;
				wf_object_arrows.markers[marker_i].pose.position.z = algo_objInfo.trcOutData[i].distZ;
				wf_object_arrows.markers[marker_i].pose.orientation.x = q_rot.getX();
				wf_object_arrows.markers[marker_i].pose.orientation.y = q_rot.getY();
				wf_object_arrows.markers[marker_i].pose.orientation.z = q_rot.getZ();
				wf_object_arrows.markers[marker_i].pose.orientation.w = q_rot.getW();
				wf_object_arrows.markers[marker_i].scale.x = algo_objInfo.trcOutData[i].length / 2 + 1.4;
				wf_object_arrows.markers[marker_i].scale.y = 0.4;
				wf_object_arrows.markers[marker_i].scale.z = 0.4;
				wf_object_arrows.markers[marker_i].color.a = 1.0;
				wf_object_arrows.markers[marker_i].color.r = 1.0;
				wf_object_arrows.markers[marker_i].color.g = 0.0;
				wf_object_arrows.markers[marker_i].color.b = 0.0;
			}
			else
			{
				wf_object_arrows.markers[marker_i].type = visualization_msgs::Marker::ARROW;
				wf_object_arrows.markers[marker_i].action = visualization_msgs::Marker::DELETE;
			}
		}
		else
		{
			wf_object_arrows.markers[marker_i].type = visualization_msgs::Marker::ARROW;
			wf_object_arrows.markers[marker_i].action = visualization_msgs::Marker::DELETE;
		}
		wf_object_roadmaps_line.markers[marker_i].header.frame_id = "image_radar";
		wf_object_roadmaps_line.markers[marker_i].header.stamp = ros::Time::now();
		wf_object_roadmaps_line.markers[marker_i].ns = nameSpace + "_roadmap_line";
		wf_object_roadmaps_line.markers[marker_i].id = i;
		wf_object_roadmaps_line.markers[marker_i].lifetime = ros::Duration(0.05);
		wf_object_roadmaps_line.markers[marker_i].points.clear();
		if (is_wf_object_roadmaps_disp_enable)
		{
			if (algo_objInfo.trcOutData[i].dynFlg >= 1 && algo_objInfo.trcOutData[i].dynFlg <= 3)
			{
				geometry_msgs::Point point;
				wf_object_roadmaps_line.markers[marker_i].type = visualization_msgs::Marker::LINE_STRIP;
				wf_object_roadmaps_line.markers[marker_i].action = visualization_msgs::Marker::ADD;
				wf_object_roadmaps_line.markers[marker_i].scale.x = 0.1;
				wf_object_roadmaps_line.markers[marker_i].color.r = 1.0;
				wf_object_roadmaps_line.markers[marker_i].color.a = 1.0;
				for (uint16_t idx = 0; idx < algo_objInfo.trcOutData[i].roadMap.num; idx++)
				{
					point.x = algo_objInfo.trcOutData[i].roadMap.points[idx].x;
					point.y = algo_objInfo.trcOutData[i].roadMap.points[idx].y;
					wf_object_roadmaps_line.markers[marker_i].points.push_back(point);
				}
			}
			else
			{
				wf_object_roadmaps_line.markers[marker_i].type = visualization_msgs::Marker::LINE_STRIP;
				wf_object_roadmaps_line.markers[marker_i].action = visualization_msgs::Marker::DELETE;
			}
		}
		else
		{
			wf_object_roadmaps_line.markers[marker_i].type = visualization_msgs::Marker::LINE_STRIP;
			wf_object_roadmaps_line.markers[marker_i].action = visualization_msgs::Marker::DELETE;
		}
		wf_object_roadmaps_point.markers[marker_i].header.frame_id = "image_radar";
		wf_object_roadmaps_point.markers[marker_i].header.stamp = ros::Time::now();
		wf_object_roadmaps_point.markers[marker_i].ns = nameSpace + "_roadmap_point";
		wf_object_roadmaps_point.markers[marker_i].id = i;
		wf_object_roadmaps_point.markers[marker_i].lifetime = ros::Duration(0.05);
		wf_object_roadmaps_point.markers[marker_i].points.clear();
		if (is_wf_object_roadmaps_disp_enable)
		{
			if (algo_objInfo.trcOutData[i].dynFlg >= 1 && algo_objInfo.trcOutData[i].dynFlg <= 3)
			{
				geometry_msgs::Point point;
				wf_object_roadmaps_point.markers[marker_i].type = visualization_msgs::Marker::POINTS;
				wf_object_roadmaps_point.markers[marker_i].action = visualization_msgs::Marker::ADD;
				wf_object_roadmaps_point.markers[marker_i].scale.x = 0.2;
				wf_object_roadmaps_point.markers[marker_i].scale.y = 0.2;
				wf_object_roadmaps_point.markers[marker_i].color.b = 1.0;
				wf_object_roadmaps_point.markers[marker_i].color.a = 1.0;
				for (uint16_t idx = 0; idx < algo_objInfo.trcOutData[i].roadMap.num; idx++)
				{
					point.x = algo_objInfo.trcOutData[i].roadMap.points[idx].x;
					point.y = algo_objInfo.trcOutData[i].roadMap.points[idx].y;
					wf_object_roadmaps_point.markers[marker_i].points.push_back(point);
				}
			}
			else
			{
				wf_object_roadmaps_point.markers[marker_i].type = visualization_msgs::Marker::POINTS;
				wf_object_roadmaps_point.markers[marker_i].action = visualization_msgs::Marker::DELETE;
			}
		}
		else
		{
			wf_object_roadmaps_point.markers[marker_i].type = visualization_msgs::Marker::POINTS;
			wf_object_roadmaps_point.markers[marker_i].action = visualization_msgs::Marker::DELETE;
		}
		wf_object_roadmapsFit_line.markers[marker_i].header.frame_id = "image_radar";
		wf_object_roadmapsFit_line.markers[marker_i].header.stamp = ros::Time::now();
		wf_object_roadmapsFit_line.markers[marker_i].ns = nameSpace + "_roadmapFit_line";
		wf_object_roadmapsFit_line.markers[marker_i].id = i;
		wf_object_roadmapsFit_line.markers[marker_i].lifetime = ros::Duration(0.05);
		wf_object_roadmapsFit_line.markers[marker_i].points.clear();
		if (is_wf_object_roadmaps_disp_enable)
		{
			if (algo_objInfo.trcOutData[i].dynFlg >= 1 && algo_objInfo.trcOutData[i].dynFlg <= 3)
			{
				geometry_msgs::Point point;
				wf_object_roadmapsFit_line.markers[marker_i].type = visualization_msgs::Marker::LINE_STRIP;
				wf_object_roadmapsFit_line.markers[marker_i].action = visualization_msgs::Marker::ADD;
				wf_object_roadmapsFit_line.markers[marker_i].scale.x = 0.1;
				wf_object_roadmapsFit_line.markers[marker_i].color.g = 1.0;
				wf_object_roadmapsFit_line.markers[marker_i].color.a = 1.0;
				for (uint16_t idx = 0; idx < algo_objInfo.trcOutData[i].roadMapFit.num; idx++)
				{
					point.x = algo_objInfo.trcOutData[i].roadMapFit.points[idx].x;
					point.y = algo_objInfo.trcOutData[i].roadMapFit.points[idx].y;
					wf_object_roadmapsFit_line.markers[marker_i].points.push_back(point);
				}
			}
			else
			{
				wf_object_roadmapsFit_line.markers[marker_i].type = visualization_msgs::Marker::LINE_STRIP;
				wf_object_roadmapsFit_line.markers[marker_i].action = visualization_msgs::Marker::DELETE;
			}
		}
		else
		{
			wf_object_roadmapsFit_line.markers[marker_i].type = visualization_msgs::Marker::LINE_STRIP;
			wf_object_roadmapsFit_line.markers[marker_i].action = visualization_msgs::Marker::DELETE;
		}
		wf_object_tags.markers[marker_i] = wf_object_boxes.markers[marker_i];
		wf_object_tags.markers[marker_i].ns = nameSpace + "_tag";
		wf_object_tags.markers[marker_i].id = i;
		wf_object_tags.markers[marker_i].type = visualization_msgs::Marker::TEXT_VIEW_FACING;
		wf_object_tags.markers[marker_i].action = visualization_msgs::Marker::ADD;
		wf_object_tags.markers[marker_i].pose.position.z += 2;
		if ((is_dynamic_obj_class_enable) && (algo_objInfo.trcOutData[i].dynFlg != 0))
		{
			wf_object_tags.markers[marker_i].pose.position.z += 8;
		}
		if ((is_wf_adas_enable) && (algo_objInfo.trcOutData[i].objBsdWarningFlag >= emWarningFlag::WarningFlag_Warning ||
									algo_objInfo.trcOutData[i].objLcaWarningFlag >= emWarningFlag::WarningFlag_Warning ||
									algo_objInfo.trcOutData[i].objDowWarningFlag >= emWarningFlag::WarningFlag_Warning ||
									algo_objInfo.trcOutData[i].objRcwWarningFlag >= emWarningFlag::WarningFlag_Warning ||
									algo_objInfo.trcOutData[i].objRctbWarningFlag >= emWarningFlag::WarningFlag_Warning ||
									algo_objInfo.trcOutData[i].objRctaWarningFlag >= emWarningFlag::WarningFlag_Warning ||
									algo_objInfo.trcOutData[i].objFctaWarningFlag >= emWarningFlag::WarningFlag_Warning ||
									algo_objInfo.trcOutData[i].objFctbWarningFlag >= emWarningFlag::WarningFlag_Warning))
		{
			wf_object_tags.markers[marker_i].color.r = 1.0f;
			wf_object_tags.markers[marker_i].color.g = 0.0f;
			wf_object_tags.markers[marker_i].color.b = 0.0f;
		}
		else
		{
			wf_object_tags.markers[marker_i].color.r = 1.0f;
			wf_object_tags.markers[marker_i].color.g = 1.0f;
			wf_object_tags.markers[marker_i].color.b = 1.0f;
		}
		wf_object_tags.markers[marker_i].scale.x = scale_text;
		wf_object_tags.markers[marker_i].scale.y = scale_text;
		wf_object_tags.markers[marker_i].scale.z = scale_text;
		std::string obj_tag_text = "";
		if (is_wf_object_tags_enable)
		{
			if (wf_referPt_enabled_TYadd)
			{
				obj_tag_text = std::to_string(arg_radar_id) + "_" + std::to_string(algo_objInfo.trcOutData[i].objType) + "_" + std::to_string(algo_objInfo.trcOutData[i].objUnqID) + "_" + std::to_string(algo_objInfo.trcOutData[i].referPt) + "_" + std::to_string(algo_objInfo.trcOutData[i].isRefPtChange);
			}
			else
			{
				obj_tag_text = std::to_string(arg_radar_id) + "_" + std::to_string(algo_objInfo.trcOutData[i].objType) + "_" + std::to_string(algo_objInfo.trcOutData[i].objUnqID);
			}
		}
		else
		{
			if ((is_wf_adas_tgu_enable) && (algo_objInfo.trcOutData[i].TGUValid > 0))
			{
				obj_tag_text = std::to_string(arg_radar_id) + "_" + std::to_string(algo_objInfo.trcOutData[i].objID) + "_TGU(" + std::to_string(algo_objInfo.trcOutData[i].TGUValid) + ")";
			}
			else
			{
				obj_tag_text = std::to_string(arg_radar_id) + "_" + std::to_string(algo_objInfo.trcOutData[i].objID);
			}
		}
		wf_object_tags.markers[marker_i].text = obj_tag_text;
		if (wf_lost_enabled)
		{
			if (algo_objInfo.trcOutData[i].lost == 0)
			{
				wf_object_tags.markers[marker_i].color.a = 1.0;
			}
			else
			{
				wf_object_tags.markers[marker_i].color.a = 0.5;
			}
		}
		wf_object_tags.markers[marker_i].lifetime = ros::Duration(0.05);
		marker_i++;
	}
	wf_object_boxes.markers.resize(marker_i);
	wf_object_arrows.markers.resize(marker_i);
	if (wf_referPt_enabled_TYadd)
	{
		wf_object_referPt.markers.resize(marker_i);
	}
	else
	{
		wf_object_referPt.markers.resize(0);
	}
	wf_object_roadmaps_line.markers.resize(marker_i);
	wf_object_roadmaps_point.markers.resize(marker_i);
	wf_object_roadmapsFit_line.markers.resize(marker_i);
	wf_object_roadmapsFit_point.markers.resize(0);
	wf_object_tags.markers.resize(marker_i);
	wf_pub_obj_vis();
	if (marker_i == 0)
	{
		ObjectListMsg_global.ObjectsBuffer.resize(1);
		arbe_msgs::wfSObj tar;
		tar.ID = -1;
		tar.RxReal = 0;
		tar.RyReal = 0;
		tar.RzReal = 0;
		tar.Spd = 0;
		tar.Ang = 0;
		tar.Rng = 0;
		tar.Vx = 0;
		tar.Vy = 0;
		tar.Vz = 0;
		tar.position.x = 0;
		tar.position.y = 0;
		tar.position.z = 0;
		tar.bounding_box.scale_x = 0;
		tar.bounding_box.scale_y = 0;
		tar.bounding_box.scale_z = 0;
		tar.power = 0;
		tar.velocity.x_dot = 0;
		tar.velocity.y_dot = 0;
		tar.velocity.velocity = 0;
		tar.objID = 0;
		tar.distX = 0;
		tar.distY = 0;
		tar.velAbsX = 0;
		tar.velAbsY = 0;
		tar.fTTC = 0;
		tar.fDDCI = 0;
		tar.objBsdWarningFlag = 0;
		tar.objLcaWarningFlag = 0;
		tar.objDowWarningFlag = 0;
		tar.objRcwWarningFlag = 0;
		tar.objRctaWarningFlag = 0;
		tar.objRctbWarningFlag = 0;
		tar.objFctaWarningFlag = 0;
		tar.objFctbWarningFlag = 0;
		ObjectListMsg_global.ObjectsBuffer[0] = tar;
	}
	else
	{
		ObjectListMsg_global.ObjectsBuffer.resize(marker_i);
	}
	ObjectListMsg_global.header.frame_id = "image_radar";
	ObjectListMsg_global.header.stamp = ros::Time::now();
	algo_object_list_for_display = ObjectListMsg_global;
	wf_objectlist_pub.publish(ObjectListMsg_global);
	ObjectListMsg_global.ObjectsBuffer.clear();
}
void wf_cluster_display_handler()
{
	std::string nameSpace = "wf_radar_" + std::to_string(arg_radar_id);
	wf_cluster_boxes.markers.clear();
	algo_clusterInfo.clusterNum;
	algo_clusterInfo.clusterData;
	int drawCluNum = 0;
	for (size_t i = 0; i < algo_clusterInfo.clusterNum; i++)
	{
		if (algo_clusterInfo.clusterData[i].useInfo == 0)
		{
			continue;
		}
		visualization_msgs::Marker clusterMarker;
		clusterMarker.header.frame_id = "image_radar";
		clusterMarker.header.stamp = ros::Time::now();
		clusterMarker.ns = nameSpace + "_cluster";
		clusterMarker.id = drawCluNum;
		clusterMarker.type = visualization_msgs::Marker::CUBE;
		clusterMarker.action = visualization_msgs::Marker::ADD;
		clusterMarker.pose.position.x = algo_clusterInfo.clusterData[i].distXDisp;
		clusterMarker.pose.position.y = algo_clusterInfo.clusterData[i].distYDisp;
		clusterMarker.pose.position.z = algo_clusterInfo.clusterData[i].distZDisp;
		clusterMarker.pose.orientation.x = 0;
		clusterMarker.pose.orientation.y = 0;
		clusterMarker.pose.orientation.z = 0;
		clusterMarker.pose.orientation.w = 1;
		clusterMarker.scale.x = std::max(fabs(algo_clusterInfo.clusterData[i].maxDistX - algo_clusterInfo.clusterData[i].minDistX), 1.0f);
		clusterMarker.scale.y = std::max(fabs(algo_clusterInfo.clusterData[i].maxDistY - algo_clusterInfo.clusterData[i].minDistY), 1.0f);
		clusterMarker.scale.z = 1.0f;
		clusterMarker.text = std::to_string(algo_clusterInfo.clusterData[i].useInfo) + "_" + std::to_string(algo_clusterInfo.clusterData[i].objectUID) + "_" + std::to_string(algo_clusterInfo.clusterData[i].clusterID);
		clusterMarker.color.r = 0.0;
		clusterMarker.color.g = 0.0;
		clusterMarker.color.b = 1.0;
		clusterMarker.color.a = 0.5;
		wf_cluster_boxes.markers.push_back(clusterMarker);
		clusterMarker.type = visualization_msgs::Marker::TEXT_VIEW_FACING;
		clusterMarker.ns = nameSpace + "_clusterTag";
		clusterMarker.text = std::to_string(algo_clusterInfo.clusterData[i].useInfo) + "_" + std::to_string(algo_clusterInfo.clusterData[i].objectUID) + "_" + std::to_string(algo_clusterInfo.clusterData[i].clusterID);
		clusterMarker.scale.x = 2;
		clusterMarker.scale.y = 2;
		clusterMarker.scale.z = 2;
		clusterMarker.color.r = 0.0;
		clusterMarker.color.g = 0.0;
		clusterMarker.color.b = 1.0;
		clusterMarker.color.a = 1.0;
		clusterMarker.pose.position.z -= 2;
		wf_cluster_boxes.markers.push_back(clusterMarker);
		visualization_msgs::Marker centerMarker;
		centerMarker.header.frame_id = "image_radar";
		centerMarker.header.stamp = ros::Time::now();
		centerMarker.ns = nameSpace + "_cluster_center";
		centerMarker.id = drawCluNum;
		centerMarker.type = visualization_msgs::Marker::SPHERE;
		centerMarker.action = visualization_msgs::Marker::ADD;
		centerMarker.pose.position.x = -algo_clusterInfo.clusterData[i].distXUse;
		centerMarker.pose.position.y = -algo_clusterInfo.clusterData[i].distYUse;
		centerMarker.pose.position.z = algo_clusterInfo.clusterData[i].distZ;
		centerMarker.pose.orientation.x = 0;
		centerMarker.pose.orientation.y = 0;
		centerMarker.pose.orientation.z = 0;
		centerMarker.pose.orientation.w = 1;
		centerMarker.scale.x = 1;
		centerMarker.scale.y = 1;
		centerMarker.scale.z = 1;
		centerMarker.color.r = 1.0;
		centerMarker.color.g = 0.0;
		centerMarker.color.b = 0.0;
		centerMarker.color.a = 0.5;
		wf_cluster_boxes.markers.push_back(centerMarker);
		drawCluNum++;
	}
	uint32_t currentClusterSize = drawCluNum < algo_ClusterNum_Max ? drawCluNum : algo_ClusterNum_Max;
	for (uint32_t i = currentClusterSize; i < algo_ClusterNum_Max; i++)
	{
		visualization_msgs::Marker clusterMarker;
		clusterMarker.header.frame_id = "image_radar";
		clusterMarker.header.stamp = ros::Time::now();
		clusterMarker.ns = nameSpace + "_cluster";
		clusterMarker.id = i;
		clusterMarker.type = visualization_msgs::Marker::CUBE;
		clusterMarker.action = visualization_msgs::Marker::DELETE;
		wf_cluster_boxes.markers.push_back(clusterMarker);
		clusterMarker.ns = nameSpace + "_clusterTag";
		clusterMarker.type = visualization_msgs::Marker::TEXT_VIEW_FACING;
		wf_cluster_boxes.markers.push_back(clusterMarker);
		visualization_msgs::Marker centerMarker;
		centerMarker.header.frame_id = "image_radar";
		centerMarker.header.stamp = ros::Time::now();
		centerMarker.ns = nameSpace + "_cluster_center";
		centerMarker.id = i;
		centerMarker.type = visualization_msgs::Marker::SPHERE;
		centerMarker.action = visualization_msgs::Marker::DELETE;
		wf_cluster_boxes.markers.push_back(centerMarker);
	}
	wf_pub_cluster_vis();
}
void stationary_display_handler(bool also_stationary_cloud, const arbe_msgs::arbePcFloatMsg::ConstPtr &global_StationaryPointCloudMsg)
{
	stationary_n_detections = 0;
	arbe_msgs::arbePcFloatMsg::ConstPtr StationaryPointCloudMsg = global_StationaryPointCloudMsg;
	if (also_stationary_cloud)
	{
		bool discard_mp_below_street_level = get_discard_below_street_level();
		bool display_stat_LM_only = get_display_stat_LM_only();
		uint32_t stationary_detections_number = StationaryPointCloudMsg->PcHeader.number_of_points;
		size_t J;
		J = 0;
		stationary_pc.clear();
		stationary_pc.width = stationary_detections_number;
		stationary_pc.points.resize(stationary_detections_number);
		total_pts = 0;
		set_reset_mapping(false);
		stationary_pc.height = 1;
		bool discard_out_of_elevation = get_discard_out_of_el_context();
		float cc_min, cc_max, span;
		Color_Coding_Min_Max::Instance()->get_values(ColoringType, cc_min, cc_max);
		if ((strcmp(ColoringType.c_str(), "Amplitude-Flat") == 0) || (strcmp(ColoringType.c_str(), "Amplitude") == 0))
		{
			memset(power_hash_table, 0, sizeof(power_hash_table));
			cc_min = 200;
			cc_max = 0;
			for (size_t i = 0; i < stationary_detections_number; i++)
			{
				float snr = RAF_COM_CALC_CalcPower(StationaryPointCloudMsg->Points.power[i]) - noise_level_db;
				if (snr < cc_min)
					cc_min = snr;
				if (snr > cc_max)
					cc_max = snr;
				if (StationaryPointCloudMsg->Points.power[i] >
					power_hash_table[(uint16_t)StationaryPointCloudMsg->Points.range_bin[i]]
									[(uint16_t)(StationaryPointCloudMsg->Points.azimuth_signed_bin[i] * 10)])
				{
					power_hash_table[(uint16_t)StationaryPointCloudMsg->Points.range_bin[i]]
									[(uint16_t)(StationaryPointCloudMsg->Points.azimuth_signed_bin[i] * 10)] = StationaryPointCloudMsg->Points.power[i];
				}
			}
			Color_Coding_Min_Max::Instance()->set_min(ColoringType, cc_min);
			Color_Coding_Min_Max::Instance()->set_max(ColoringType, cc_max);
		}
		span = cc_max - cc_min;
		bool warn_once = false;
		for (size_t i = 0; i < stationary_detections_number; i++)
		{
			if (StationaryPointCloudMsg->Points.range_bin[i] <= 0)
			{
				if (!warn_once)
					ROS_WARN("STAT CLOUD ON RADAR %d: range bin <= 0. frame number = %d. number of points = %d", arg_radar_id, StationaryPointCloudMsg->PcHeader.frame_counter, detections_number);
				warn_once = true;
				continue;
			}
			stationary_pc.points[J].elevation = StationaryPointCloudMsg->Points.elevation_signed_bin[i] *
												StationaryPointCloudMsg->PcMetadata.PcResolution.elevation_coefficient;
			stationary_pc.points[J].azimuth = StationaryPointCloudMsg->Points.azimuth_signed_bin[i] *
											  StationaryPointCloudMsg->PcMetadata.PcResolution.azimuth_coefficient;
			stationary_pc.points[J].range = ((StationaryPointCloudMsg->Points.range_bin[i] - StationaryPointCloudMsg->PcMetadata.range_offset) *
											 StationaryPointCloudMsg->PcMetadata.PcResolution.range_resolution);
			stationary_pc.points[J].doppler = StationaryPointCloudMsg->Points.doppler_signed_bin[i] * StationaryPointCloudMsg->PcMetadata.PcResolution.doppler_resolution;
			if ((stationary_pc.points[J].doppler > MaxDoppler) || (stationary_pc.points[J].doppler < MinDoppler))
			{
				continue;
			}
			if ((strcmp(ColoringType.c_str(), "Amplitude-Flat") == 0) &&
				(StationaryPointCloudMsg->Points.power[i] != power_hash_table[(uint16_t)StationaryPointCloudMsg->Points.range_bin[i]]
																			 [(uint16_t)(StationaryPointCloudMsg->Points.azimuth_signed_bin[i] * 10)]))
			{
				continue;
			}
			TaregtCartesian targetCartesian;
			targetCartesian.x = stationary_pc.points[J].range * stationary_pc.points[J].azimuth;
			targetCartesian.z = stationary_pc.points[J].range * stationary_pc.points[J].elevation;
			targetCartesian.y = sqrt(stationary_pc.points[J].range * stationary_pc.points[J].range - targetCartesian.x * targetCartesian.x - targetCartesian.z * targetCartesian.z);
			Eigen::Vector3f one_point(targetCartesian.x, targetCartesian.y, targetCartesian.z);
			one_point = *transform_p * one_point;
			targetCartesian.x = one_point[0];
			targetCartesian.z = one_point[2];
			targetCartesian.y = one_point[1];
			if ((discard_mp_below_street_level && ((StationaryPointCloudMsg->Points.flag_bits[i] & arbe_msgs::arbePcFlagBitsEnum::PC_FLAG_BELOW_STREET_LVL) > 0)) ||
				(display_stat_LM_only && ((StationaryPointCloudMsg->Points.flag_bits[i] & arbe_msgs::arbePcFlagBitsEnum::STAT_FLAG_IS_LM) == 0)) ||
				((display_stat_LM_only == false) && ((StationaryPointCloudMsg->Points.flag_bits[i] & arbe_msgs::arbePcFlagBitsEnum::STAT_FLAG_IS_LM) > 0)) ||
				(aggOnlyCoreStat && is_localization_active && ((StationaryPointCloudMsg->Points.flag_bits[i] & arbe_msgs::arbePcFlagBitsEnum::STAT_FLAG_IS_CORE_STATIONARY)) == 0))
			{
				continue;
			}
			if (discard_out_of_elevation)
			{
				float abs_z = targetCartesian.z + radar_z_offset;
				float z_min, z_max;
				Color_Coding_Min_Max::Instance()->get_values("Elevation", z_min, z_max);
				if (abs_z < z_min || abs_z > z_max)
					continue;
			}
			stationary_pc.points[J].x = targetCartesian.x;
			stationary_pc.points[J].y = targetCartesian.y;
			if (strcmp(ColoringType.c_str(), "Amplitude-Flat") == 0)
				stationary_pc.points[J].z = 0;
			else
				stationary_pc.points[J].z = targetCartesian.z;
			stationary_pc.points[J].power = RAF_COM_CALC_CalcPower(StationaryPointCloudMsg->Points.power[i]);
			if (strcmp(ColoringType.c_str(), "Range/Doppler") == 0)
			{
				if (StationaryPointCloudMsg->Points.azimuth_signed_bin[i] != selectedAzimuthBin)
					continue;
				stationary_pc.points[J].x = stationary_pc.points[J].doppler;
				stationary_pc.points[J].y = stationary_pc.points[J].range;
				stationary_pc.points[J].z = RAF_COM_CALC_CalcPower(StationaryPointCloudMsg->Points.power[i] - noise_level_db);
			}
			else
			{
				if (strcmp(ColoringType.c_str(), "Amplitude-Flat") == 0)
					stationary_pc.points[J].z = 0;
				else
					stationary_pc.points[J].z = targetCartesian.z;
			}
			stationary_pc.points[J].range_bin = StationaryPointCloudMsg->Points.range_bin[i];
			stationary_pc.points[J].elevation_bin = StationaryPointCloudMsg->Points.elevation_signed_bin[i];
			stationary_pc.points[J].azimuth_bin = StationaryPointCloudMsg->Points.azimuth_signed_bin[i];
			stationary_pc.points[J].doppler_bin = StationaryPointCloudMsg->Points.doppler_signed_bin[i];
			stationary_pc.points[J].power_value = StationaryPointCloudMsg->Points.power[i];
			stationary_pc.points[J].timestamp_sec = (uint32_t)(StationaryPointCloudMsg->PcHeader.time / 1000);
			stationary_pc.points[J].timestamp_nsec = (uint32_t)(StationaryPointCloudMsg->PcHeader.time % 1000) * 1000000;
			stationary_pc.points[J].snr = RAF_COM_CALC_CalcPower(StationaryPointCloudMsg->Points.power[i]) - noise_level_db;
			if (!StationaryPointCloudMsg->Points.phase.empty())
			{
				stationary_pc.points[J].phase_value = StationaryPointCloudMsg->Points.phase[i];
			}
			stationary_pc.points[J].az_backoff = StationaryPointCloudMsg->Points.az_backoff[i];
			stationary_pc.points[J].el_backoff = StationaryPointCloudMsg->Points.el_backoff[i];
			stationary_pc.points[J].track_id = StationaryPointCloudMsg->Points.track_id[i];
			stationary_pc.points[J].cluster_id = StationaryPointCloudMsg->Points.cluster_id[i];
			stationary_pc.points[J].flag_bits = StationaryPointCloudMsg->Points.flag_bits[i];
			if (one_color_frame == 0)
			{
				pointcloud_color(stationary_pc, J, cc_min, cc_max, span, ColoringType, ego_velocity, -radar_yaw_angle);
			}
			else
			{
			}
			J++;
			stationary_n_detections++;
		}
		stationary_pc.width = J;
		stationary_pc.height = 1;
		stationary_pc.points.resize(stationary_pc.width * stationary_pc.height);
		total_pts += StationaryPointCloudMsg->Points.power.size();
		stationaty_output.header.stamp = ros::Time::now();
		pcl::toROSMsg(stationary_pc, stationaty_output);
		stationaty_output.header.frame_id = "image_radar";
		stationary_pcl_pub.publish(stationaty_output);
		J = stationary_pc.points.size();
		uint32_t stationary_detections = StationaryPointCloudMsg->PcHeader.number_of_points;
		detections_number += stationary_detections;
	}
	else if (!get_disp_processed_pc() && clear_stationary_once)
	{
		clear_stationary_once = false;
		set_reset_mapping(false);
		stationaty_output.header.stamp = ros::Time::now();
		pcl::toROSMsg(stationary_pc, stationaty_output);
		stationaty_output.header.frame_id = "image_radar";
		stationary_pcl_pub.publish(stationaty_output);
		stationary_pc.clear();
		stationary_pc.width = 0;
		stationary_pc.points.resize(0);
	}
}
void clear_slam_markers()
{
	slam_boxes.markers.clear();
	slam_arrows.markers.clear();
	slam_tags.markers.clear();
}
void set_disp_objects(bool flag)
{
	ros::NodeHandle n("~");
	ros::NodeHandle n_cam("~");
	n.setCallbackQueue(&pc_disp_queue[IND_FOR_PC_OBJ]);
	n_cam.setCallbackQueue(&cam_disp_queue[IND_FOR_CAM_OBJ]);
	if (disp_objects == flag)
		return;
	disp_objects = flag;
	if (disp_objects)
	{
		objects_sub = n.subscribe("/arbe/processed/objects/" + std::to_string(arg_radar_id), 1, slam_read_callback);
		objects_cam_sub = n_cam.subscribe("/arbe/processed/objects/" + std::to_string(arg_radar_id), 1, slam_read_cam_callback);
	}
	else
	{
		clear_slam_markers();
		objects_sub.shutdown();
		set_slam_valid(false);
		ego_velocity = 0;
		hostHeadingUnc = -1;
		hostHeading = 0;
	}
}
void set_disp_FS(bool displayFS)
{
	if (is_FS_display_active == displayFS)
	{
		return;
	}
	if (displayFS && fabs(sin(arg_radar_yaw_angle * M_PI / 180.0)) <= sin(5.0 * M_PI / 180.0))
	{
		ros::NodeHandle n("~");
		n.setCallbackQueue(&pc_disp_queue[IND_FOR_PC_FS]);
		fs_display_sub = n.subscribe("/arbe/processed/free_space/display_polygon/" + std::to_string(arg_radar_id), 1, FS_disp_CB);
		is_FS_display_active = true;
	}
	else
	{
		is_FS_display_active = false;
		transformed_FS_polygon.polygon.points.clear();
		fs_poly_pub.publish(transformed_FS_polygon);
		fs_display_sub.shutdown();
	}
}
void remove_fs_polygon()
{
	if (is_FS_display_active)
	{
		transformed_FS_polygon.polygon.points.clear();
		fs_poly_pub.publish(transformed_FS_polygon);
	}
}
void projectFS(geometry_msgs::PolygonStamped &fs_display, float scale, std::vector<cv::Point> &polygons)
{
	cv::Point pt;
	for (uint16_t i = 0; i < fs_display.polygon.points.size(); i++)
	{
		geometry_msgs::Point32 point = fs_display.polygon.points.at(i);
		float xzyw[4] = {point.x, -point.z, point.y, 1};
		float out[3] = {0, 0, 0};
		for (uint16_t out_dim = 0; out_dim < 3; out_dim++)
		{
			for (uint16_t inner_dim = 0; inner_dim < 4; inner_dim++)
			{
				out[out_dim] += prj[out_dim][inner_dim] * xzyw[inner_dim];
			}
		}
		pt = cv::Point(out[0] / out[2] * scale + cols_offset, out[1] / out[2] * scale + rows_offset);
		polygons.push_back(pt);
	}
}
void set_disp_data(bool displayData, bool disp_processed_pc_l, bool disp_objects)
{
	set_disp_pc(displayData, disp_processed_pc_l);
	set_disp_objects(disp_objects);
	set_disp_FS(displayData);
}
void radars_installation_params_callback(const arbe_msgs::arbeSettingsPerRadar::ConstPtr &msg)
{
	if (msg->n_radars > arg_radar_id)
	{
		bool recalc = false;
		ROS_DEBUG("Set pitch to %f", msg->ant_pitch[arg_radar_id]);
		if (radar_pitch_angle != msg->ant_pitch[arg_radar_id])
		{
			radar_pitch_angle = msg->ant_pitch[arg_radar_id];
			recalc = true;
		}
		ROS_DEBUG("Set yaw to %f", msg->ant_yaw[arg_radar_id]);
		if (radar_yaw_angle != -msg->ant_yaw[arg_radar_id])
		{
			radar_yaw_angle = -msg->ant_yaw[arg_radar_id];
			recalc = true;
		}
		ROS_DEBUG("Set antenna height to %f", msg->ant_pitch[arg_radar_id]);
		if (radar_z_offset != msg->ant_height[arg_radar_id])
		{
			radar_z_offset = msg->ant_height[arg_radar_id];
			recalc = true;
		}
		ROS_DEBUG("Set x-offset to %f", msg->offset_x[arg_radar_id]);
		if (radar_x_offset != msg->offset_x[arg_radar_id])
		{
			radar_x_offset = msg->offset_x[arg_radar_id];
			recalc = true;
		}
		ROS_DEBUG("Set y-offset to %f", msg->offset_y[arg_radar_id]);
		if (radar_y_offset != msg->offset_y[arg_radar_id])
		{
			radar_y_offset = msg->offset_y[arg_radar_id];
			recalc = true;
		}
		if (recalc)
			calc_transform_matrix();
	}
}
void gui_controls_callback(const arbe_msgs::arbeGUIsettings::ConstPtr &controls_data)
{
	if ((ros::Time::now() - controls_data->header.stamp).toSec() > 1)
		return;
	ROS_DEBUG("Set MinDoppler to %lf", controls_data->MinDoppler);
	MinDoppler = controls_data->MinDoppler;
	ROS_DEBUG("Set MaxDoppler to %lf", controls_data->MaxDoppler);
	MaxDoppler = controls_data->MaxDoppler;
	ROS_DEBUG("Set Color_Coding_Min_Max min:%lf max:%lf", controls_data->coloring_cc_min, controls_data->coloring_cc_max);
	Color_Coding_Min_Max::Instance()->set_min(controls_data->ColoringType, controls_data->coloring_cc_min);
	Color_Coding_Min_Max::Instance()->set_max(controls_data->ColoringType, controls_data->coloring_cc_max);
	ROS_DEBUG("Set coloring to %s", controls_data->ColoringType.c_str());
	if (ColoringType != controls_data->ColoringType)
	{
		ColoringType = controls_data->ColoringType;
		calc_Coloring();
	}
	ROS_DEBUG("Set color detection by track id %d", controls_data->colorPointcloudByTrackId);
	set_color_pc_by_track(controls_data->colorPointcloudByTrackId);
	ROS_DEBUG("Set discardOutOfElContext %d", controls_data->discardOutOfElContext);
	set_discard_out_of_el_context(controls_data->discardOutOfElContext);
	ROS_DEBUG("Set discardMpDynDetections %d", controls_data->discardMpDynDetections);
	set_discard_mp_dyn_detections(controls_data->discardMpDynDetections);
	ROS_DEBUG("Set discardBelowStreetLevel %d", controls_data->discardBelowStreetLevel);
	set_discard_below_street_level(controls_data->discardBelowStreetLevel);
	ROS_DEBUG("Set displayStatLmOnly %d", controls_data->displayStatLmOnly);
	set_display_stat_LM_only(controls_data->displayStatLmOnly);
	ROS_DEBUG("Set applyFilterDynPc %d", controls_data->applyFilterDynPc);
	set_apply_filter_dyn_pc(controls_data->applyFilterDynPc);
	ROS_DEBUG("Set noise_level_db to %d", controls_data->noise_level_db);
	noise_level_db = controls_data->noise_level_db;
	ROS_DEBUG("Set signal_flag to %d", controls_data->signal_flag);
	signal_flag = controls_data->signal_flag;
	ROS_DEBUG("Set selectedAzimuthBin to %d", controls_data->selectedAzimuthBin);
	selectedAzimuthBin = controls_data->selectedAzimuthBin;
	ROS_DEBUG("Set localization_active to %d", controls_data->localization_active);
	is_localization_active = controls_data->localization_active;
	ROS_DEBUG("NUM RADARS in MSG %d", controls_data->per_radar.n_radars);
	marker_text_size = controls_data->marker_text_size;
	ROS_DEBUG("Set data display to %d", controls_data->per_radar.display_data[arg_radar_id]);
	set_disp_data(controls_data->per_radar.display_data[radar_index], controls_data->disp_processed_pc, controls_data->disp_slam);
	if (controls_data->per_radar.n_radars > arg_radar_id)
	{
		bool recalc = false;
		ROS_DEBUG("Set pitch to %f", controls_data->per_radar.ant_pitch[arg_radar_id]);
		if (radar_pitch_angle != controls_data->per_radar.ant_pitch[arg_radar_id])
		{
			radar_pitch_angle = controls_data->per_radar.ant_pitch[arg_radar_id];
			recalc = true;
		}
		ROS_DEBUG("Set antenna height to %f", controls_data->per_radar.ant_pitch[arg_radar_id]);
		if (radar_z_offset != controls_data->per_radar.ant_height[arg_radar_id])
		{
			radar_z_offset = controls_data->per_radar.ant_height[arg_radar_id];
			recalc = true;
		}
		if (recalc)
			calc_transform_matrix();
		if (floating_text_enabled && (controls_data->per_radar.radar_for_text == -1 || is_localization_active))
			expunge_text = true;
		bool prev_floating_text = floating_text_enabled;
		floating_text_enabled = arg_radar_id == controls_data->per_radar.radar_for_text;
		if (!prev_floating_text && floating_text_enabled)
			reset_fps_calc();
	}
	if (ros::Time::now().toSec() - controls_data->header.stamp.toSec() < 3)
		slamDisplaySettings = controls_data->slam_display;
	set_colorObjByClass(controls_data->color_obj_by_class);
	aggOnlyCoreStat = controls_data->aggregate_only_core;
	if (is_wf_postprocess_enable != controls_data->wf_postprocess)
	{
		const bool prev_postprocess_enable = is_wf_postprocess_enable;
		is_wf_postprocess_enable = controls_data->wf_postprocess;
		if (is_wf_postprocess_enable == true)
		{
			resetAlgoParam = true;
			algo_InitFlg = 1;
		}
		else
		{
			clear_wf_algorithm_object_markers();
		}
		if (!is_wf_postprocess_enable && prev_postprocess_enable && is_wf_adas_enable)
		{
			adas_warn_status.data.assign(16, 0);
			adas_warn_status.data[0] = static_cast<uint8_t>(arg_radar_id);
			wf_adas_warn_status_pub.publish(adas_warn_status);
		}
	}
	if (is_wf_pointcloud_enable != controls_data->wf_pointcloud)
	{
		is_wf_pointcloud_enable = controls_data->wf_pointcloud;
		if (is_wf_pointcloud_enable == true)
		{
		}
		else
		{
			is_clear_adas_marker_flag = true;
			pointCloud_data_clear();
		}
	}
	if (is_radar_dynamic_obj_enable != controls_data->wf_dynamic_point_obj)
	{
		is_radar_dynamic_obj_enable = controls_data->wf_dynamic_point_obj;
	}
	if (is_radar_static_obj_enable != controls_data->wf_static_point_obj)
	{
		is_radar_static_obj_enable = controls_data->wf_static_point_obj;
	}
	is_radar_dynamic_point_enable = controls_data->wf_radar_dynamic_point;
	is_radar_static_point_enable = controls_data->wf_radar_static_point;
	is_wf_object_tags_enable = controls_data->wf_object_tags;
	if (is_wf_cluster_disp_enable != controls_data->wf_cluster)
	{
		is_wf_cluster_disp_enable = controls_data->wf_cluster;
		if (!is_wf_cluster_disp_enable)
		{
			wf_cluster_clear();
		}
	}
	is_wf_cluster_disp_enable = false;
	if (is_wf_adas_enable != controls_data->wf_Adas)
	{
		is_wf_adas_enable = controls_data->wf_Adas;
		if (!is_wf_adas_enable)
			is_clear_adas_marker_flag = true;
	}
	if (is_wf_adas_bsd_enable != controls_data->wf_Adas_Bsd)
	{
		is_wf_adas_bsd_enable = controls_data->wf_Adas_Bsd;
		if (!is_wf_adas_bsd_enable)
		{
			is_clear_adas_marker_flag = true;
		}
	}
	if (is_wf_adas_lca_enable != controls_data->wf_Adas_Lca)
	{
		is_wf_adas_lca_enable = controls_data->wf_Adas_Lca;
		if (!is_wf_adas_lca_enable)
		{
			is_clear_adas_marker_flag = true;
		}
	}
	if (is_wf_adas_rcta_enable != controls_data->wf_Adas_Rcta)
	{
		is_wf_adas_rcta_enable = controls_data->wf_Adas_Rcta;
		if (!is_wf_adas_rcta_enable)
		{
			is_clear_adas_marker_flag = true;
		}
	}
	if (is_wf_adas_dow_enable != controls_data->wf_Adas_Dow)
	{
		is_wf_adas_dow_enable = controls_data->wf_Adas_Dow;
		if (!is_wf_adas_dow_enable)
			is_clear_adas_marker_flag = true;
	}
	if (is_wf_adas_rcw_enable != controls_data->wf_Adas_Rcw)
	{
		is_wf_adas_rcw_enable = controls_data->wf_Adas_Rcw;
		if (!is_wf_adas_rcw_enable)
			is_clear_adas_marker_flag = true;
	}
	if (is_wf_adas_rctb_enable != controls_data->wf_Adas_Rctb)
	{
		is_wf_adas_rctb_enable = controls_data->wf_Adas_Rctb;
		if (!is_wf_adas_rctb_enable)
			is_clear_adas_marker_flag = true;
	}
	if (is_wf_adas_fcta_enable != controls_data->wf_Adas_Fcta)
	{
		is_wf_adas_fcta_enable = controls_data->wf_Adas_Fcta;
		if (!is_wf_adas_fcta_enable)
			is_clear_adas_marker_flag = true;
	}
	if (is_wf_adas_fctb_enable != controls_data->wf_Adas_Fctb)
	{
		is_wf_adas_fctb_enable = controls_data->wf_Adas_Fctb;
		if (!is_wf_adas_fctb_enable)
			is_clear_adas_marker_flag = true;
	}
	if (is_wf_adas_curb_enable != controls_data->wf_Adas_Curb)
	{
		is_wf_adas_curb_enable = controls_data->wf_Adas_Curb;
		if (!is_wf_adas_curb_enable)
			is_clear_adas_curb_flag = true;
	}
	is_wf_adas_curb_enable = false;
	if (is_clear_adas_curb_flag)
	{
		wf_adas_curb_clear();
		is_clear_adas_curb_flag = false;
	}
	if (is_clear_adas_marker_flag)
	{
		wf_adas_clear();
		is_clear_adas_marker_flag = false;
	}
	if (is_wf_adas_bsd_enable || is_wf_adas_lca_enable || is_wf_adas_rcta_enable || is_wf_adas_dow_enable ||
		is_wf_adas_rcw_enable || is_wf_adas_rctb_enable || is_wf_adas_fcta_enable || is_wf_adas_fctb_enable)
		is_wf_adas_enable = true;
	is_wf_tracdisp_enable = controls_data->wf_TracDisp;
	if (is_wf_raw_sgu_display_enable != controls_data->wf_raw_sgu_display)
	{
		is_wf_raw_sgu_display_enable = controls_data->wf_raw_sgu_display;
		if (!is_wf_raw_sgu_display_enable)
		{
			clear_raw_sgu_object_markers();
		}
	}
	if (!is_wf_tracdisp_enable)
	{
		clear_wf_algorithm_object_markers();
		clear_raw_sgu_object_markers();
	}
	is_radar_class_size_enable = controls_data->wf_tunnel_disp;
	is_static_obj_class_enable = controls_data->wf_static_obj_class;
	is_dynamic_obj_class_enable = controls_data->dynamic_obj_class;
	if (is_wf_wf_data_pause != controls_data->wf_Data_Pause)
	{
		is_wf_wf_data_pause = controls_data->wf_Data_Pause;
		if (is_wf_wf_data_pause == false)
		{
			resetAlgoParam = true;
			algo_InitFlg = 1;
		}
	}
	return;
}
void slam_enable_callback(const arbe_msgs::arbeBoolWithTimePtr &enableSlamMsg)
{
	if (ros::Time::now().toSec() - enableSlamMsg->header.stamp.toSec() < 3)
	{
		is_slam_active = enableSlamMsg->flag;
		if (is_slam_active == false)
		{
			clear_slam_markers();
		}
	}
}
void legacy_pc_inject_enable_cllback(const arbe_msgs::arbeBoolWithTimePtr &enableLegacyPcInject)
{
	read_legacy_processed_pc = enableLegacyPcInject->flag;
	if (read_legacy_processed_pc == false)
		return;
	ros::NodeHandle n("~");
	n.setCallbackQueue(&pc_disp_queue[IND_FOR_PC_INJECT]);
	if (disp_processed_pc == true)
	{
		stationary_targets_sub.shutdown();
		targets_sub.shutdown();
	}
}
void FS_disp_CB(const geometry_msgs::PolygonStamped::ConstPtr &FS_disp)
{
	if (!FS_in_use)
		FS_display_polygon = geometry_msgs::PolygonStamped(*FS_disp);
	if (!transformed_FS_in_use)
	{
		transformed_FS_polygon = geometry_msgs::PolygonStamped(FS_display_polygon);
		fs_display_handler();
	}
}
void choose_fs_disp_callback(const std_msgs::Bool::ConstPtr &msg)
{
	fs_from_gui = msg->data;
	transformed_FS_in_use = !msg->data;
	if (transformed_FS_in_use)
	{
		remove_fs_polygon();
	}
}
void prj_receive_CB(const std_msgs::Float32MultiArray::ConstPtr &msg)
{
	for (uint8_t i = 0; i < 3; i++)
		for (uint8_t j = 0; j < 4; j++)
		{
			prj[i][j] = msg->data[4 * i + j];
		}
	scale_ref = msg->data[12];
	rows_offset = msg->data[13];
	cols_offset = msg->data[14];
}
void calc_camera_transform_CB(const arbe_msgs::arbeCameraInstallationParams::ConstPtr &msg)
{
	arbe_msgs::arbeCameraInstallationParams::Ptr cam_params(new arbe_msgs::arbeCameraInstallationParams());
	cam_params->intrinsic = msg->intrinsic;
	cam_params->extrinsic_trans = msg->extrinsic_trans;
	cam_params->euler_a_b_g = msg->euler_a_b_g;
	calc_camera_intrinsic(cam_params);
	calc_camera_extrinsic(cam_params);
	camera_transform = intrinsic * extrinsic;
}
void SI_slam_on_cam_callback(const sensor_msgs::CompressedImage::ConstPtr &image)
{
	if (!is_wf_wf_data_pause)
	{
		cam_image = sensor_msgs::CompressedImage::ConstPtr(image);
		is_cam_frame_available = true;
	}
}
void single_color_callback(const std_msgs::UInt32::ConstPtr &msg)
{
	one_color_add(msg->data * 20);
}
void restore_defaults_callback(const std_msgs::Bool::ConstPtr &msg)
{
	radar_yaw_angle = -arg_radar_yaw_angle * M_PI / 180;
	calc_transform_matrix();
}
void fix_installation_callback(const std_msgs::Float32::ConstPtr &msg)
{
	radar_yaw_angle = (msg->data - arg_radar_yaw_angle) * M_PI / 180;
	calc_transform_matrix();
	one_color_add();
}
void legacy_target_read_callback(const arbe_msgs::arbeNewPcMsg::ConstPtr &LegacyPcMsg, int pc_type)
{
	arbe_msgs::arbePcFloatMsg::Ptr PointCloudFloatMsg(new arbe_msgs::arbePcFloatMsg());
	arbe_msgs::arbePcFloatBins pcFloatBins;
	bool is_phase_exists = LegacyPcMsg->Points.phase.size() > 0 ? true : false;
	PointCloudFloatMsg->RosHeader = LegacyPcMsg->RosHeader;
	PointCloudFloatMsg->RosHeader.stamp = ros::Time::now();
	PointCloudFloatMsg->PcHeader = LegacyPcMsg->PcHeader;
	PointCloudFloatMsg->PcMetadata = LegacyPcMsg->PcMetadata;
	for (uint32_t pc_ind = 0; pc_ind < LegacyPcMsg->PcHeader.number_of_points; pc_ind++)
	{
		pcFloatBins.azimuth_signed_bin.push_back((float)LegacyPcMsg->Points.azimuth_signed_bin[pc_ind]);
		pcFloatBins.range_bin.push_back((float)LegacyPcMsg->Points.range_bin[pc_ind]);
		pcFloatBins.doppler_signed_bin.push_back((float)LegacyPcMsg->Points.doppler_signed_bin[pc_ind]);
		pcFloatBins.elevation_signed_bin.push_back((float)LegacyPcMsg->Points.elevation_signed_bin[pc_ind]);
		pcFloatBins.power.push_back((float)LegacyPcMsg->Points.power[pc_ind]);
		if (is_phase_exists == true)
		{
			pcFloatBins.phase.push_back((float)LegacyPcMsg->Points.phase[pc_ind]);
		}
		else
		{
			pcFloatBins.phase.push_back(0.0);
		}
		pcFloatBins.confidence.push_back(0);
		pcFloatBins.flag_bits.push_back(0);
		pcFloatBins.cluster_id.push_back(0);
		pcFloatBins.track_id.push_back(0);
		pcFloatBins.extra_info.push_back(0);
		pcFloatBins.reserved.push_back(0);
		pcFloatBins.az_backoff.push_back(0);
		pcFloatBins.el_backoff.push_back(0);
		pcFloatBins.rcs_above_min.push_back(0);
	}
	PointCloudFloatMsg->Points = pcFloatBins;
}
void slam_read_callback(const arbe_msgs::arbeSlamMsg::ConstPtr &msg)
{
	slamMsg = arbe_msgs::arbeSlamMsg::ConstPtr(msg);
	is_slam_frame_available = true;
}
void slam_read_cam_callback(const arbe_msgs::arbeSlamMsg::ConstPtr &msg)
{
	slamMsg_cam = arbe_msgs::arbeSlamMsg::ConstPtr(msg);
	is_cam_slam_frame_available = true;
}
void master_slam_read_callback(const arbe_msgs::arbeSlamMsg::ConstPtr &msg)
{
	masterSlamMsg = arbe_msgs::arbeSlamMsg::ConstPtr(msg);
	is_master_slam_frame_available = true;
}
void road_inclination_callback(const arbe_msgs::arbeRdInclinationConstPtr &msg)
{
	rd_inc.lastUpdateTime = msg->header.stamp;
	rd_inc.rd_ls_a = msg->ant_tilt;
	rd_inc.rd_ls_b = msg->ant_height;
}
void gui_message_callback(const std_msgs::String::ConstPtr &msg)
{
	ROS_DEBUG("visualization_node: I heard: [%s]", msg->data.c_str());
	std::string msg_str = msg->data;
	std::size_t pos = msg_str.find("goodbye");
	if (pos != std::string::npos)
	{
		ROS_DEBUG("Received a goodbye command from the GUI node... stopping");
		terminating = true;
	}
}
void change_text_phi_callback(const std_msgs::Float32::ConstPtr &msg)
{
	dtections_per_frame_marker.pose.position.x = -10 * sin(msg->data);
	dtections_per_frame_marker.pose.position.y = 10 * cos(msg->data);
}
void front_side_slam_triggered_callback(const std_msgs::Bool::ConstPtr &trigger)
{
}
void side_slam_triggered_callback(const std_msgs::Bool::ConstPtr &trigger)
{
	triggered_slam = trigger->data;
	set_disp_objects(trigger->data);
	if (trigger->data && fs_from_gui)
		choose_fs_disp_callback(trigger);
	else if (!trigger->data && fs_from_gui)
	{
		choose_fs_disp_callback(trigger);
		fs_from_gui = true;
	}
	if (!trigger->data)
	{
		clear_stationary_once = true;
		slam_transform = pcl_transform;
	}
}
bool CompareRecords(const ArbePointXYZRGBGeneric &a, const ArbePointXYZRGBGeneric &b)
{
	if (a.azimuth < b.azimuth)
		return true;
	else if (a.azimuth > b.azimuth)
		return false;
	else if (a.range > b.range)
		return false;
	return false;
}
void calc_camera_intrinsic(const arbe_msgs::arbeCameraInstallationParams::Ptr &msg)
{
	intrinsic << msg->intrinsic[0], msg->intrinsic[3], msg->intrinsic[6],
		msg->intrinsic[1], msg->intrinsic[4], msg->intrinsic[7],
		msg->intrinsic[2], msg->intrinsic[5], msg->intrinsic[8];
}
void calc_camera_extrinsic(const arbe_msgs::arbeCameraInstallationParams::Ptr &msg)
{
	extrinsic.translation() << msg->extrinsic_trans[0], msg->extrinsic_trans[1], msg->extrinsic_trans[2];
	extrinsic.rotate(Eigen::AngleAxisf(msg->euler_a_b_g[0], Eigen::Vector3f::UnitX()));
	extrinsic.rotate(Eigen::AngleAxisf(msg->euler_a_b_g[1], Eigen::Vector3f::UnitZ()));
	extrinsic.rotate(Eigen::AngleAxisf(msg->euler_a_b_g[2], Eigen::Vector3f::UnitX()));
}
arbe_msgs::arbeCameraInstallationParams::Ptr cam_transform_defaults()
{
	arbe_msgs::arbeCameraInstallationParams::Ptr cam_params(new arbe_msgs::arbeCameraInstallationParams());
	float intr[] = {1526.97, 0, 934.05,
					0, 1533.03, 537.37,
					0, 0, 1};
	std::vector<float> intrinsic_vec(intr, intr + sizeof(intr) / sizeof(float));
	float trans[] = {0, 0.08, 0.02};
	std::vector<float> translation(trans, trans + sizeof(trans) / sizeof(float));
	float eul[] = {0, 0, 0};
	std::vector<float> euler(eul, eul + sizeof(eul) / sizeof(float));
	cam_params->intrinsic = intrinsic_vec;
	cam_params->extrinsic_trans = translation;
	cam_params->euler_a_b_g = euler;
	return cam_params;
}
void calc_camera_transform(arbe_msgs::arbeCameraInstallationParams::Ptr &msg)
{
	calc_camera_intrinsic(msg);
	calc_camera_extrinsic(msg);
	camera_transform = intrinsic * extrinsic;
}
static cv::Point project(float X, float Y, float Z, float scale, float &cam_z)
{
	float xzyw[4] = {X, -Z, Y, 1};
	float out[3] = {0, 0, 0};
	for (uint8_t out_dim = 0; out_dim < 3; out_dim++)
	{
		for (uint8_t inner_dim = 0; inner_dim < 4; inner_dim++)
		{
			out[out_dim] += prj[out_dim][inner_dim] * xzyw[inner_dim];
		}
	}
	cam_z = out[2];
	cv::Point pt = cv::Point(out[0] / out[2] * scale + cols_offset, out[1] / out[2] * scale + rows_offset);
	return pt;
}
static std::vector<cv::Point> makeFace(cv::Point p1, cv::Point p2, cv::Point p3, cv::Point p4)
{
	std::vector<cv::Point> face;
	face.push_back(p1);
	face.push_back(p2);
	face.push_back(p3);
	face.push_back(p4);
	return face;
}
static std::vector<cv::Point> makeLine(cv::Point p1, cv::Point p2)
{
	std::vector<cv::Point> line;
	line.push_back(p1);
	line.push_back(p2);
	return line;
}
static void makeBoundingBox(std::vector<cv::Point> &bb_points, std::vector<std::vector<cv::Point>> &polygons)
{
	polygons.push_back(makeFace(bb_points[0], bb_points[1], bb_points[2], bb_points[3]));
	polygons.push_back(makeFace(bb_points[4], bb_points[5], bb_points[6], bb_points[7]));
	polygons.push_back(makeLine(bb_points[0], bb_points[4]));
	polygons.push_back(makeLine(bb_points[1], bb_points[5]));
	polygons.push_back(makeLine(bb_points[2], bb_points[6]));
	polygons.push_back(makeLine(bb_points[3], bb_points[7]));
}
static void object2boundingBox(arbe_msgs::arbeTSlamObj object, cv::Point &tl, int rows, int cols, bool &legit, float scale, std::vector<std::vector<cv::Point>> &polygons)
{
	legit = true;
	uint8_t out = 0;
	float x = object.position.x;
	float depth = object.position.y;
	float up = object.position.z;
	float size_x = object.bounding_box.scale_x;
	float size_y = object.bounding_box.scale_y;
	float size_z = object.bounding_box.scale_z;
	float X, Y, Z;
	float orientation = object.bounding_box.orientation;
	float co = cos(orientation);
	float so = sin(orientation);
	std::vector<cv::Point> points;
	float top = 1000000;
	float left = 1000000;
	float cam_z;
	cv::Point pt;
	for (uint8_t i = 0; i < 8; i++)
	{
		X = x + (primitive[pr_x[i]] * size_x * co + primitive[pr_y[i]] * size_y * so) / 2;
		Y = depth + (primitive[pr_y[i]] * size_y * co - primitive[pr_x[i]] * size_x * so) / 2;
		Z = (up + primitive[pr_z[i]] * size_z / 2);
		if (Y < 0)
			out = 8;
		pt = project(X, Y, Z, scale, cam_z);
		if (pt.y > rows || pt.y < 0 || pt.x > cols || pt.x < 0)
			out++;
		points.push_back(pt);
		left = pt.x < left ? pt.x : left;
		top = pt.y < top ? pt.y : top;
	}
	tl.x = left;
	tl.y = top;
	if (out > 4)
		legit = false;
	else
		makeBoundingBox(points, polygons);
}
void hadnle_SI_slam_on_cam()
{
	sensor_msgs::CompressedImage::ConstPtr image_local = cam_image;
	if (is_cam_frame_available == false)
	{
		return;
	}
	is_cam_frame_available = false;
	if (slamDisplaySettings.slam_on_camera && get_slam_valid())
	{
		cv_bridge::CvImagePtr cv_ptr;
		cv_ptr = cv_bridge::toCvCopy(image_local, sensor_msgs::image_encodings::BGR8);
		cv::Point pt2text;
		int cols = cv_ptr->image.cols;
		int rows = cv_ptr->image.rows;
		float scale = scale_ref < 0 ? 1.0 : rows / scale_ref;
		std::vector<std::vector<cv::Point>> polygons;
		bool draw;
		bool eco_mode = slamDisplaySettings.disp_slam_eco_mode;
		bool color_by_class = slamDisplaySettings.color_by_class;
		FS_in_use = true;
		int n_pts = FS_display_polygon.polygon.points.size();
		if (n_pts > 0 && slamDisplaySettings.disp_FS_on_cam)
		{
			cv::Mat layer = cv_ptr->image.clone();
			std::vector<cv::Point> fs_polygon;
			projectFS(FS_display_polygon, scale, fs_polygon);
			std::vector<std::vector<cv::Point>> fillContAll;
			fillContAll.push_back(fs_polygon);
			cv::fillPoly(layer, fillContAll, cv::Scalar(90, 255, 50));
			cv::addWeighted(cv_ptr->image, 0.7, layer, 0.3, 0.0, cv_ptr->image);
		}
		FS_in_use = false;
		arbe_msgs::arbeSlamMsg::ConstPtr localSlam = arbe_msgs::arbeSlamMsg::ConstPtr(slamMsg_cam);
		if (arg_radar_id == 0 && get_slam_valid() && slamDisplaySettings.disp_funnel)
		{
			uint8_t n_segments = 5;
			float vel = localSlam->meta_data.HostVelocity, omega = localSlam->meta_data.HostOmega;
			if (fabs(omega) * 180 / 3.1415 < 0.0000001)
			{
				int8_t sgn = omega > 0 ? 1 : -1;
				omega = 0.0000001 * sgn;
			}
			float DT = 1.0;
			if (vel * 3.6 > 60)
			{
				DT -= vel * 3.6 / 120;
				DT = DT < 0.3 ? 0.3 : DT;
			}
			float dt = DT / n_segments;
			float cam_z;
			if (vel > 5 / 3.6)
			{
				double y0 = 1 > vel * dt / 2 ? 1 : vel * dt / 2;
				double circ_center = vel / omega;
				double radius = sqrt(circ_center * circ_center + vel * dt * vel * dt / 4);
				omega = -omega;
				double delta_angle = atan(dt * omega) * 2;
				double angle = -delta_angle / 2;
				if (omega < 0)
					angle += M_PI;
				cv::Point pt_r = project(cos(angle) * radius + circ_center + 1, y0, -1, scale, cam_z);
				cv::Point pt_l = project(cos(angle) * radius + circ_center - 1, y0, -1, scale, cam_z);
				for (uint8_t section = 0; section < n_segments; section++)
				{
					angle += delta_angle;
					double Y = sin(angle) * radius;
					double X = cos(angle) * radius + circ_center;
					double Z = rd_inc.rd_ls_a * Y + rd_inc.rd_ls_b;
					cv::Point pt2_r = project(X + 1, Y, Z, scale, cam_z);
					cv::Point pt2_l = project(X - 1, Y, Z, scale, cam_z);
					cv::line(cv_ptr->image, pt_r, pt2_r, cv::Scalar(0, 0, 255), 2);
					cv::line(cv_ptr->image, pt_l, pt2_l, cv::Scalar(0, 0, 255), 2);
					pt_r = pt2_r;
					pt_l = pt2_l;
				}
			}
		}
		uint16_t n_objects;
		arbe_msgs::arbeSlamMsg localNeighbor;
		for (int8_t nbr = -1; nbr < MAX_RADARS; nbr++)
		{
			if (nbr == -1)
			{
				n_objects = localSlam->meta_data.NumberOfObjects;
			}
			else if (!is_valid_neighbor[nbr])
				continue;
			else
			{
				localNeighbor = arbe_msgs::arbeSlamMsg(neighbor_msg[nbr]);
				n_objects = localNeighbor.meta_data.NumberOfObjects;
			}
			for (size_t i = 0; i < n_objects; i++)
			{
				arbe_msgs::arbeTSlamObj object;
				if (nbr == -1)
				{
					object = localSlam->ObjectsBuffer[i];
				}
				else
				{
					object = localNeighbor.ObjectsBuffer[i];
					object.bounding_box.orientation -= delta_phi[nbr];
					Eigen::Vector3f objx(object.position.x, object.position.y, object.position.z);
					objx = nbr_transform[nbr] * objx;
					if (objx[1] < 0)
						continue;
					object.position.x = objx[0];
					object.position.y = objx[1];
					object.position.z = objx[2];
				}
				int16_t cls2show = get_classes_to_show();
				if (cls2show != -1 && cls2show != object.obj_class)
					continue;
				if (object.obj_conf < 0.5)
					continue;
				std::string fc_txt = "";
				float red, green, blue;
				Slam_Color::Instance()->get_class_color(object.obj_class, red, green, blue, fc_txt);
				if (!eco_mode)
					polygons.clear();
				object2boundingBox(object, pt2text, rows, cols, draw, scale, polygons);
				if (!eco_mode)
				{
					if (!draw)
						continue;
					if (!color_by_class)
						Slam_Color::Instance()->get_color(object.ID, red, green, blue);
					uint8_t r, g, b;
					r = (uint8_t)(255 * red);
					g = (uint8_t)(255 * green);
					b = (uint8_t)(255 * blue);
					float renorm_depth = 3.0 / 80 * Fixed2Float(object.position.y, 7) + 3;
					int thickness = round(6 * scale);
					thickness = thickness < 2 ? 2 : thickness;
					thickness = thickness > 10 ? 10 : thickness;
					cv::polylines(cv_ptr->image, polygons, true, cv::Scalar(b, g, r), thickness);
					std::string txt = std::to_string(object.ID);
					if (slamDisplaySettings.disp_dist_on_cam)
					{
						float x = object.position.x;
						float y = object.position.y;
						uint16_t dis_to_obj = (uint16_t)(round(sqrt(x * x + y * y)));
						txt = std::to_string(dis_to_obj) + " m";
					}
					txt = txt + fc_txt;
				}
			}
			if (eco_mode)
			{
				cv::polylines(cv_ptr->image, polygons, true, cv::Scalar(53, 255, 255), 5);
			}
		}
		arbe_capture_pub.publish(cv_ptr->toCompressedImageMsg());
	}
	else
	{
		arbe_capture_pub.publish(image_local);
	}
}
void calc_nbr_transform_matrix(uint8_t rdr_id, float dphi, float dpitch, float dx, float dy, float dz)
{
	dpitch = 0;
	nbr_transform[rdr_id] = Eigen::Affine3f::Identity();
	nbr_transform[rdr_id].rotate(Eigen::AngleAxisf(dphi, Eigen::Vector3f::UnitZ()));
	nbr_transform[rdr_id].rotate(Eigen::AngleAxisf(dpitch, Eigen::Vector3f::UnitX()));
	Eigen::Vector3f translation(dx, dy, dz);
	translation = nbr_transform[rdr_id] * translation;
	nbr_transform[rdr_id].translation() = translation;
}
void calc_transform_matrix()
{
	pcl_transform = Eigen::Affine3f::Identity();
	pcl_transform.rotate(Eigen::AngleAxisf(radar_yaw_angle, Eigen::Vector3f::UnitZ()));
	pcl_transform.rotate(Eigen::AngleAxisf(radar_pitch_angle, Eigen::Vector3f::UnitX()));
	Eigen::Vector3f translation(radar_x_offset, radar_y_offset, radar_z_offset);
	pcl_transform.translation() = translation;
}
void calc_slam_transform()
{
	slam_transform = Eigen::Affine3f::Identity();
	slam_transform.translation()[0] = local_cart_x;
	slam_transform.translation()[1] = local_cart_y;
	slam_transform.rotate(Eigen::AngleAxisf(hostHeading, Eigen::Vector3f::UnitZ()));
	slam_transform = slam_transform * pcl_transform;
}
void reset_fps_calc()
{
	write_i_t = 0;
	read_i_t = 0;
	n_fps = 0;
}
float calculate_fps(uint64_t timestamp_ms)
{
	uint64_t Now = timestamp_ms;
	t_vec[write_i_t++] = Now;
	float delta = (float)(Now - t_vec[read_i_t]);
	n_fps += n_fps < FPS_CALC_LENGTH ? 1 : 0;
	write_i_t %= FPS_CALC_LENGTH;
	if (n_fps == FPS_CALC_LENGTH)
	{
		read_i_t++;
		read_i_t %= FPS_CALC_LENGTH;
	}
	return n_fps / (delta / 1000 + 1e-5);
}
void handle_pc_frame()
{
	bool is_pc_available;
	avaliable_frmae_mutex.lock();
	is_pc_available = is_pc_frame_available;
	avaliable_frmae_mutex.unlock();
	if (is_wf_tracdisp_enable)
		wf_pub_obj_vis();
	if (is_pc_available == true)
	{
		avaliable_frmae_mutex.lock();
		is_pc_frame_available = false;
		avaliable_frmae_mutex.unlock();
	}
	else if (is_clear_PC_frame_on)
	{
		pc_shutdown_clear();
		stationary_pc_shutdown_clear();
		is_clear_PC_frame_on = false;
	}
}
int16_t get_classes_to_show()
{
	return classes_to_show;
}
void set_classes_to_show(int16_t cls)
{
	classes_to_show = cls;
}
size_t get_num_objects()
{
	if (slamMsg)
		return slamMsg->ObjectsBuffer.size();
	else
		return 0;
}
arbe_msgs::arbeTSlamObj get_object(uint16_t i)
{
	return slamMsg->ObjectsBuffer[i];
}
bool get_colorObjByClass()
{
	return colorObjectsByClass;
}
void set_colorObjByClass(bool flag)
{
	colorObjectsByClass = flag;
}
arbe_msgs::arbeTSlamMetadata get_slam_metadata()
{
	return slamMsg->meta_data;
}
void fs_display_handler()
{
	Eigen::Affine3f local_transform;
	if (get_disp_processed_pc())
	{
		local_transform = slam_transform;
	}
	else
	{
		local_transform = pcl_transform;
	}
	transformed_FS_in_use = true;
	for (size_t p = 0; p < transformed_FS_polygon.polygon.points.size(); p++)
	{
		Eigen::Vector3f one_point(transformed_FS_polygon.polygon.points[p].x, transformed_FS_polygon.polygon.points[p].y, transformed_FS_polygon.polygon.points[p].z);
		one_point = local_transform * one_point;
		transformed_FS_polygon.polygon.points[p].x = one_point[0];
		transformed_FS_polygon.polygon.points[p].z = one_point[2];
		transformed_FS_polygon.polygon.points[p].y = one_point[1];
	}
	if (is_FS_display_active)
	{
		fs_poly_pub.publish(transformed_FS_polygon);
		transformed_FS_in_use = false;
	}
}
void pub_slam_vis()
{
	marker_pub.publish(slam_arrows);
	marker_pub.publish(slam_tags);
	marker_pub.publish(slam_boxes);
}
void slam_display_handler()
{
	uint32_t shape = visualization_msgs::Marker::CUBE;
	uint32_t arrow_shape = visualization_msgs::Marker::ARROW;
	tf2::Quaternion q_rot;
	int16_t cls2show = get_classes_to_show();
	slam_boxes.markers.resize(get_num_objects());
	slam_arrows.markers.resize(get_num_objects());
	slam_tags.markers.resize(get_num_objects());
	uint32_t num_dis_objs = 0;
	for (uint32_t i = 0, marker_i = 0; i < get_num_objects(); i++)
	{
		arbe_msgs::arbeTSlamObj slam_obj = get_object(i);
		if (cls2show != -1 && cls2show != slam_obj.obj_class)
			continue;
		if (slam_obj.obj_conf < 0.5)
			continue;
		slam_boxes.markers[marker_i].header.frame_id = "image_radar";
		slam_boxes.markers[marker_i].header.stamp = ros::Time::now();
		slam_boxes.markers[marker_i].ns = "radar_object";
		slam_boxes.markers[marker_i].id = slam_obj.ID;
		if (slam_obj.ID == 0)
			slam_boxes.markers[marker_i].id += i;
		slam_boxes.markers[marker_i].type = shape;
		slam_boxes.markers[marker_i].action = visualization_msgs::Marker::ADD;
		float orientation = slam_obj.bounding_box.orientation;
		Eigen::Vector3f objx(slam_obj.position.x, slam_obj.position.y, slam_obj.position.z);
		objx = slam_transform * objx;
		float orientation_f;
		if (is_localization_active)
		{
			orientation_f = orientation - hostHeading;
		}
		else
		{
			orientation_f = orientation;
		}
		slam_boxes.markers[marker_i].pose.position.x = objx[0];
		slam_boxes.markers[marker_i].pose.position.y = objx[1];
		slam_boxes.markers[marker_i].pose.position.z = objx[2];
		double r = 0, p = 0, y = M_PI_2 - orientation_f + radar_yaw_angle;
		q_rot.setRPY(r, p, y);
		tf2::convert(q_rot, slam_boxes.markers[marker_i].pose.orientation);
		slam_boxes.markers[marker_i].scale.x = slam_obj.bounding_box.scale_y;
		slam_boxes.markers[marker_i].scale.y = slam_obj.bounding_box.scale_x;
		slam_boxes.markers[marker_i].scale.z = slam_obj.bounding_box.scale_z;
		float red, green, blue;
		if (get_colorObjByClass())
		{
			std::string fc_txt;
			Slam_Color::Instance()->get_class_color(slam_obj.obj_class, red, green, blue, fc_txt);
		}
		else
		{
			Slam_Color::Instance()->get_color(slam_obj.ID, red, green, blue);
		}
		if (one_color_frame > 0)
		{
			red = (arg_radar_id * 100) % 256;
			green = (160 + arg_radar_id * 50) % 256;
			blue = (240 + arg_radar_id * 50) % 256;
		}
		slam_boxes.markers[marker_i].color.r = red;
		slam_boxes.markers[marker_i].color.g = green;
		slam_boxes.markers[marker_i].color.b = blue;
		slam_boxes.markers[marker_i].color.a = 0.5;
		std::string id_text = std::to_string(slam_obj.ID);
		slam_boxes.markers[marker_i].text = id_text;
		slam_boxes.markers[marker_i].lifetime = ros::Duration(0.05);
		marker_i++;
		num_dis_objs++;
	}
	for (uint32_t i = 0, marker_i = 0; i < get_num_objects(); i++)
	{
		arbe_msgs::arbeTSlamObj slam_obj = get_object(i);
		if (cls2show != -1 && cls2show != slam_obj.obj_class)
			continue;
		slam_arrows.markers[marker_i] = slam_boxes.markers[marker_i];
		slam_arrows.markers[marker_i].type = arrow_shape;
		float y_vel = slam_obj.velocity.y_dot + ego_velocity;
		float arrow_sc = sqrt(slam_obj.velocity.x_dot * slam_obj.velocity.x_dot + y_vel * y_vel) / 60 * 3.6 * 3;
		arrow_sc = arrow_sc > 3 ? 3 : arrow_sc;
		arrow_sc = arrow_sc < 0.1 ? 0 : arrow_sc;
		slam_arrows.markers[marker_i].scale.x = arrow_sc + slam_obj.bounding_box.scale_y / 2;
		slam_arrows.markers[marker_i].scale.y = 0.2;
		slam_arrows.markers[marker_i].scale.z = 0.2;
		slam_arrows.markers[marker_i].id = slam_obj.ID + 100;
		if (slam_obj.ID == 0)
			slam_boxes.markers[marker_i].id += i;
		slam_arrows.markers[marker_i].action = visualization_msgs::Marker::ADD;
		slam_arrows.markers[marker_i].color.r = 0.0f;
		slam_arrows.markers[marker_i].color.g = 0.0f;
		slam_arrows.markers[marker_i].color.b = 10.0f;
		slam_arrows.markers[marker_i].color.a = 1.0;
		slam_arrows.markers[marker_i].lifetime = ros::Duration(0.05);
		marker_i++;
	}
	for (uint32_t i = 0, marker_i = 0; i < get_num_objects(); i++)
	{
		arbe_msgs::arbeTSlamObj slam_obj = get_object(i);
		if (cls2show != -1 && cls2show != slam_obj.obj_class)
			continue;
		float scale_text = 2;
		slam_tags.markers[marker_i] = slam_boxes.markers[marker_i];
		slam_tags.markers[marker_i].id = slam_obj.ID + 1000;
		if (slam_obj.ID == 0)
			slam_boxes.markers[marker_i].id += i;
		slam_tags.markers[marker_i].type = visualization_msgs::Marker::TEXT_VIEW_FACING;
		slam_tags.markers[marker_i].action = visualization_msgs::Marker::ADD;
		slam_tags.markers[marker_i].pose.position.z += slam_obj.bounding_box.scale_z / 2 + 5 * scale_text / 8;
		slam_tags.markers[marker_i].scale.z = scale_text;
		slam_tags.markers[marker_i].color.r = 1.0f;
		slam_tags.markers[marker_i].color.g = 1.0f;
		slam_tags.markers[marker_i].color.b = 1.0f;
		slam_tags.markers[marker_i].color.a = 1.0;
		slam_tags.markers[marker_i].lifetime = ros::Duration(0.05);
		marker_i++;
	}
	slam_boxes.markers.resize(num_dis_objs);
	slam_arrows.markers.resize(num_dis_objs);
	slam_tags.markers.resize(num_dis_objs);
	pub_slam_vis();
}
void handle_slam_frame()
{
	if (is_slam_frame_available == false)
	{
		if (disp_objects == true)
		{
			pub_slam_vis();
		}
		return;
	}
	is_slam_frame_available = false;
	arbe_msgs::arbeSlamMsg::ConstPtr local_slamMsg;
	if (is_localization_active && arg_radar_id != 0)
		local_slamMsg = masterSlamMsg;
	else
		local_slamMsg = slamMsg;
	ego_velocity = local_slamMsg->meta_data.HostVelocity;
	hostHeadingUnc = local_slamMsg->meta_data.HostHeadingUnc;
	if (hostHeadingUnc > 0)
		hostHeading = local_slamMsg->meta_data.HostHeading;
	local_cart_x = local_slamMsg->meta_data.local_catr_x;
	local_cart_y = local_slamMsg->meta_data.local_catr_y;
	if (is_localization_active)
		calc_slam_transform();
	else
		slam_transform = pcl_transform;
	set_slam_valid(true);
	slam_display_handler();
}
void *si_slam_cam_thread(void *args)
{
	ros::Rate loop_rate(45);
	while (ros::ok())
	{
		hadnle_SI_slam_on_cam();
		spin_cam_display();
		loop_rate.sleep();
	}
	return args;
}
void prepare_basic_markers(void)
{
	dtections_per_frame_marker.header.frame_id = "image_radar";
	dtections_per_frame_marker.ns = "radar_dtections_per_frame_marker";
	dtections_per_frame_marker.id = 10006;
	dtections_per_frame_marker.type = visualization_msgs::Marker::TEXT_VIEW_FACING;
	dtections_per_frame_marker.action = visualization_msgs::Marker::ADD;
	dtections_per_frame_marker.pose.position.x = 0;
	dtections_per_frame_marker.pose.position.y = -10;
	dtections_per_frame_marker.pose.position.z = 1;
	dtections_per_frame_marker.pose.orientation.x = 0.0;
	dtections_per_frame_marker.pose.orientation.y = 0.0;
	dtections_per_frame_marker.pose.orientation.z = 0.0;
	dtections_per_frame_marker.pose.orientation.w = 1.0;
	dtections_per_frame_marker.scale.x = marker_text_size;
	dtections_per_frame_marker.scale.y = marker_text_size;
	dtections_per_frame_marker.scale.z = marker_text_size;
	dtections_per_frame_marker.color.r = 1.0f;
	dtections_per_frame_marker.color.g = 1.0f;
	dtections_per_frame_marker.color.b = 1.0f;
	dtections_per_frame_marker.color.a = 1.0;
}
void one_color_add(uint32_t n_frames)
{
	one_color_frame += n_frames;
}
void neighbor_slam_msg_callback(const arbe_msgs::arbeSlamMsg::ConstPtr &msg, uint32_t neig_radar_id)
{
	neighbor_msg[neig_radar_id] = arbe_msgs::arbeSlamMsg(*msg);
}
void neighbor_radar_install_param_msg_callback(const std_msgs::Float32MultiArrayConstPtr &msg, uint32_t radar_id)
{
	ros::NodeHandle n_cam("~");
	n_cam.setCallbackQueue(&cam_disp_queue[IND_FOR_CAM_NEIGHBOR]);
	if (radar_id > MAX_RADARS)
	{
		ROS_WARN("RECEIVED RADAR POSITION MSG WITH ILLEGAL INDEX = %d", radar_id);
		return;
	}
	neighbor_radar_install_params[radar_id].x_offset = msg->data[0];
	neighbor_radar_install_params[radar_id].y_offset = msg->data[1];
	neighbor_radar_install_params[radar_id].z_offset = msg->data[2];
	neighbor_radar_install_params[radar_id].yaw_in_rads = msg->data[3] * M_PI / 180.0;
	float my_yaw = arg_radar_yaw_angle * M_PI / 180.0;
	float my_x = sin(my_yaw);
	float my_y = cos(my_yaw);
	float his_x = sin(neighbor_radar_install_params[radar_id].yaw_in_rads);
	float his_y = cos(neighbor_radar_install_params[radar_id].yaw_in_rads);
	float dot_prod = my_x * his_x + my_y * his_y;
	was_radar_install_parmas_rcv[radar_id] = true;
	if (dot_prod > 0)
	{
		is_valid_neighbor[radar_id] = true;
		neighbor_slam_objects_sub[radar_id] = n_cam.subscribe<arbe_msgs::arbeSlamMsg>("/arbe/processed/objects/" + std::to_string(radar_id), 2, boost::bind(neighbor_slam_msg_callback, _1, radar_id));
		delta_phi[radar_id] = my_yaw - neighbor_radar_install_params[radar_id].yaw_in_rads;
		float delta_x_pos = neighbor_radar_install_params[radar_id].x_offset - arg_radar_x_offset;
		float delta_y_pos = neighbor_radar_install_params[radar_id].y_offset - arg_radar_y_offset;
		float delta_z_pos = neighbor_radar_install_params[radar_id].z_offset - arg_radar_z_offset;
		calc_nbr_transform_matrix(radar_id, delta_phi[radar_id], 0, delta_x_pos, delta_y_pos, delta_z_pos);
	}
}
void param_init_track()
{
	for (int i = 0; i < 15; i++)
	{
		algo_GPS_data[i] = 0;
	}
	algo_eleAng = 0;
}
void corner_radar_controls_read_callback(const std_msgs::Float32MultiArray::ConstPtr &msg)
{
	if (msg->data[0] != radar_index)
	{
		return;
	}
	arg_radar_x_offset = msg->data[1];
	arg_radar_y_offset = msg->data[2];
	arg_radar_z_offset = msg->data[3];
	arg_radar_yaw_angle = msg->data[4];
	arg_radar_pitch_angle = msg->data[5];
	algo_setAng = arg_radar_yaw_angle;
	algo_eleAng = arg_radar_pitch_angle;
	algo_RadarPos.m_mountingPosition.radar_x_offset = arg_radar_x_offset;
	algo_RadarPos.m_mountingPosition.radar_y_offset = arg_radar_y_offset;
	algo_RadarPos.m_mountingPosition.radar_z_offset = arg_radar_z_offset;
	algo_RadarPos.m_mountingPosition.radar_yaw_angle = arg_radar_yaw_angle;
	algo_RadarPos.m_mountingPosition.radar_pitch_angle = arg_radar_pitch_angle;
	s_menuAziValue = arg_radar_yaw_angle;
	s_menuEleValue = arg_radar_pitch_angle;
}
void egoCarSpdCoef_callback(const std_msgs::Float32MultiArray::ConstPtr &msg)
{
	arg_egoCarSpdCoefk_value = msg->data[0];
}
void calib_update_info_callback(const std_msgs::Float32MultiArray::ConstPtr &msg)
{
	if (switch_type == 2)
	{
		ROS_INFO("calib_update_info_callback");
		if (msg->data[7] != arg_radar_id)
		{
			return;
		}
		bag_az_angle = msg->data[0];
		bag_el_angle = msg->data[1];
	}
}
void calib_type_callback(const std_msgs::Float32MultiArray::ConstPtr &msg)
{
	switch_type = msg->data[0];
}
void GetWaveID(const arbe_msgs::wfTiFrameRD::ConstPtr &msg)
{
	waveIDG = msg->waveID;
}
void hardResetForBagSwitchIfNeeded()
{
	bool force_reset_on_bag_switch = false;
	ros::param::param<bool>("/kpi/force_reset_on_bag_switch", force_reset_on_bag_switch, false);
	if (!force_reset_on_bag_switch)
	{
		return;
	}

	int bag_switch_epoch = 0;
	if (!ros::param::get("/kpi/bag_switch_epoch", bag_switch_epoch))
	{
		return;
	}
	if (g_last_bag_switch_epoch < 0)
	{
		g_last_bag_switch_epoch = bag_switch_epoch;
		return;
	}
	if (bag_switch_epoch == g_last_bag_switch_epoch)
	{
		return;
	}
	g_last_bag_switch_epoch = bag_switch_epoch;
	algo_InitFlg = 1;
	resetAlgoParam = true;
	algo_timeFrm = 0.0f;
	RosbagTimeStamp = 0.0;
	TimeStamp = 0.0;
	frame_counter = 0;
	detections_number = 0;
	algo_TagtTrc_Trc_Dat_Num = 0;
	algo_objInfo.trcNum = 0;
	reSetCarData();
	ROS_WARN("KPI replay hard reset on bag switch: epoch=%d radar=%d", bag_switch_epoch, arg_radar_id);
}
void corner_radar_post_process_data_callback(const arbe_msgs::wfAutosarData::ConstPtr &msg)
{
	// 1. 接收一帧回灌 LGU 数据；播放器暂停时不处理该帧。
	if (is_wf_wf_data_pause)
		return;
	hardResetForBagSwitchIfNeeded();
	frame_counter = msg->frameID;
	detections_number = msg->LGUNum;
	cloud_corner.points.resize(detections_number);
	mAlgoPerOutputPtr = (PERInfoOutStruct *)msg->outputData.data();
	// 原始 SGU 仅复制到独立显示缓存，绝不写入 algo_objInfo 或算法输入。
	if (is_wf_raw_sgu_display_enable)
	{
		update_raw_sgu_display_cache();
	}

	// 2. 解析 LGU 点迹并转换到车辆显示坐标系，再按距离由近到远排序，和 Hh 保持一致。
	float azimuth_radian, elevation_radian;
	int j = 0;
	for (size_t i = 0; i < detections_number; i++)
	{
		if (algo_RadarPos.m_mountingPosition.orientation == 1)
		{
			azimuth_radian = -(mAlgoPerOutputPtr->dotTrans[j].angAzi / 100.0f) * M_PI / 180.0f;
			elevation_radian = -(mAlgoPerOutputPtr->dotTrans[j].angEle / 100.0f) * M_PI / 180.0f;
			cloud_corner.points[j].azimuth = mAlgoPerOutputPtr->dotTrans[j].angAzi / 100.0f;
			cloud_corner.points[j].elevation = mAlgoPerOutputPtr->dotTrans[j].angEle / 100.0f;
		}
		else if (algo_RadarPos.m_mountingPosition.orientation == 2)
		{
			azimuth_radian = (mAlgoPerOutputPtr->dotTrans[j].angAzi / 100.0f) * M_PI / 180.0f;
			elevation_radian = (mAlgoPerOutputPtr->dotTrans[j].angEle / 100.0f) * M_PI / 180.0f;
			cloud_corner.points[j].azimuth = mAlgoPerOutputPtr->dotTrans[j].angAzi / 100.0f;
			cloud_corner.points[j].elevation = mAlgoPerOutputPtr->dotTrans[j].angEle / 100.0f;
		}
		else
		{
			if ((arg_radar_id == 2) || (arg_radar_id == 3))
			{
				azimuth_radian = -(mAlgoPerOutputPtr->dotTrans[j].angAzi / 100.0f) * M_PI / 180.0f;
				elevation_radian = -(mAlgoPerOutputPtr->dotTrans[j].angEle / 100.0f) * M_PI / 180.0f;
				cloud_corner.points[j].azimuth = mAlgoPerOutputPtr->dotTrans[j].angAzi / 100.0f;
				cloud_corner.points[j].elevation = mAlgoPerOutputPtr->dotTrans[j].angEle / 100.0f;
			}
			else
			{
				azimuth_radian = (mAlgoPerOutputPtr->dotTrans[j].angAzi / 100.0f) * M_PI / 180.0f;
				elevation_radian = (mAlgoPerOutputPtr->dotTrans[j].angEle / 100.0f) * M_PI / 180.0f;
				cloud_corner.points[j].azimuth = mAlgoPerOutputPtr->dotTrans[j].angAzi / 100.0f;
				cloud_corner.points[j].elevation = mAlgoPerOutputPtr->dotTrans[j].angEle / 100.0f;
			}
		}

		cloud_corner.points[j].doppler = mAlgoPerOutputPtr->dotTrans[j].vel / 100.0f;
		cloud_corner.points[j].range = mAlgoPerOutputPtr->dotTrans[j].dist / 100.0f;
		cloud_corner.points[j].az_amb = mAlgoPerOutputPtr->dotTrans[j].is_azi_amb_detected;
		cloud_corner.points[j].az_angle_qly = mAlgoPerOutputPtr->dotTrans[j].thetaQly;
		cloud_corner.points[j].el_amb = 0;
		cloud_corner.points[j].el_angle_qly = mAlgoPerOutputPtr->dotTrans[j].phiQly;
		cloud_corner.points[j].exist_prob = 0;
		cloud_corner.points[j].loc_peer_idx = mAlgoPerOutputPtr->dotTrans[j].idxLocPeer;
		cloud_corner.points[j].meas_status = 0;
		cloud_corner.points[j].noise = mAlgoPerOutputPtr->dotTrans[j].power - mAlgoPerOutputPtr->dotTrans[j].snr;
		cloud_corner.points[j].rcs_est = mAlgoPerOutputPtr->dotTrans[j].RCS;
		cloud_corner.points[j].signal = mAlgoPerOutputPtr->dotTrans[j].power;
		cloud_corner.points[j].vel_qly = mAlgoPerOutputPtr->dotTrans[j].dvQly;
		float az = azimuth_radian + (arg_radar_yaw_angle + mAlgoPerOutputPtr->calibInfoTrans.finalAziResult) * M_PI / 180.0f;
		float el = elevation_radian + (arg_radar_pitch_angle + mAlgoPerOutputPtr->calibInfoTrans.finalEleResult) * M_PI / 180.0f;
		cloud_corner.points[j].x = cloud_corner.points[j].range * cos(az) + arg_radar_x_offset;
		cloud_corner.points[j].y = cloud_corner.points[j].range * sin(az) + arg_radar_y_offset;
		cloud_corner.points[j].z = cloud_corner.points[j].range * sin(el) + arg_radar_z_offset;
		cloud_corner.points[j].id = j;
		cloud_corner.points[j].radar_id = arg_radar_id;
		if (strcmp(ColoringType.c_str(), "Doppler") == 0)
		{
			pointcloud_color_new(cloud_corner, j, MinDoppler, MaxDoppler, ColoringType);
		}
		else
		{
			pointcloud_one_color(cloud_corner, j, (0 + arg_radar_id * 100) % 256, (183 + arg_radar_id * 50) % 256, (235 + arg_radar_id * 50) % 256);
		}
		j++;
	}

	detections_number = j;
	std::sort(cloud_corner.points.begin(), cloud_corner.points.begin() + detections_number,
		[](const CornerRadarPointXYZRGBGeneric& p1, const CornerRadarPointXYZRGBGeneric& p2) {
			return p1.range < p2.range;
		});

	for (size_t i = 0; i < detections_number; ++i)
	{
		algo_bagData.bagData[i].d = cloud_corner.points[i].range;
		algo_bagData.bagData[i].v = cloud_corner.points[i].doppler;
		algo_bagData.bagData[i].theta = cloud_corner.points[i].azimuth;
		algo_bagData.bagData[i].phi = cloud_corner.points[i].elevation;
		algo_bagData.bagData[i].dVar = 0;
		algo_bagData.bagData[i].vVar = 0;
		algo_bagData.bagData[i].dvCov = 0;
		algo_bagData.bagData[i].thetaVar = 0;
		algo_bagData.bagData[i].phiVar = 0;
		algo_bagData.bagData[i].Rcs = cloud_corner.points[i].rcs_est;
		algo_bagData.bagData[i].sig = cloud_corner.points[i].signal;
		algo_bagData.bagData[i].noi = cloud_corner.points[i].noise;
		algo_bagData.bagData[i].thetaQly = cloud_corner.points[i].az_angle_qly;
		algo_bagData.bagData[i].phiQly = cloud_corner.points[i].el_angle_qly;
		algo_bagData.bagData[i].dvQly = cloud_corner.points[i].vel_qly;
		algo_bagData.bagData[i].measStatus = cloud_corner.points[i].meas_status;
		algo_bagData.bagData[i].idxLocPeer = cloud_corner.points[i].loc_peer_idx;
		algo_bagData.bagData[i].existProb = cloud_corner.points[i].exist_prob;
		algo_bagData.bagData[i].is_azi_amb_detected = cloud_corner.points[i].az_amb;
		algo_bagData.bagData[i].is_ele_amb_detected = cloud_corner.points[i].el_amb;
	}

	// 3. 将排序后的点云转换为算法点迹输入容器。
	algo_cdi_number = detections_number;
	algo_bagData.dotNum = detections_number;
	cloud_corner.height = 1;
	cloud_corner.width = detections_number;
	cloud_corner.points.resize(cloud_corner.width * cloud_corner.height);
	pcl::toROSMsg(cloud_corner, output);
	output.header.frame_id = "image_radar";
	output.header.stamp = ros::Time::now();
	if (!is_wf_postprocess_enable)
	{
		corner_radar_pcl_pub.publish(output);
	}
	// 4. HIL 模式下，使用回灌载荷中的 SGU 目标作为算法目标输入。
	//    额外补充的参考点/高度字段仅用于显示默认值，不改变 Hh 的 ADAS 输入字段。
	if (0 != HILMODEL)
	{
		int k = 0;
		for (int i = 0; i < mAlgoPerOutputPtr->SGUNum; ++i)
		{
			if ((mAlgoPerOutputPtr->objTrans[i].objID == 0) &&
				(fabs(mAlgoPerOutputPtr->objTrans[i].distX / 100.0f) < 0.01f))
			{
				continue;
			}

			algo_objInfo.trcOutData[k].objID = mAlgoPerOutputPtr->objTrans[i].objID;
			algo_objInfo.trcOutData[k].objType = mAlgoPerOutputPtr->objTrans[i].objType;
			algo_objInfo.trcOutData[k].distX = mAlgoPerOutputPtr->objTrans[i].distX / 100.0f;
			algo_objInfo.trcOutData[k].distY = mAlgoPerOutputPtr->objTrans[i].distY / 100.0f;
			algo_objInfo.trcOutData[k].distZ = 0.0f;
			algo_objInfo.trcOutData[k].distXRefer = algo_objInfo.trcOutData[k].distX;
			algo_objInfo.trcOutData[k].distYRefer = algo_objInfo.trcOutData[k].distY;
			algo_objInfo.trcOutData[k].dynFlg = mAlgoPerOutputPtr->objTrans[i].dynFlg;
			algo_objInfo.trcOutData[k].length = mAlgoPerOutputPtr->objTrans[i].length / 100.0f;
			algo_objInfo.trcOutData[k].width = mAlgoPerOutputPtr->objTrans[i].width / 100.0f;
			algo_objInfo.trcOutData[k].height = 1.0f;
			algo_objInfo.trcOutData[k].yawAng = mAlgoPerOutputPtr->objTrans[i].yawAng / 100.0f;
			algo_objInfo.trcOutData[k].yawAngRefer = algo_objInfo.trcOutData[k].yawAng;
			algo_objInfo.trcOutData[k].velX = mAlgoPerOutputPtr->objTrans[i].velX / 100.0f;
			algo_objInfo.trcOutData[k].velY = mAlgoPerOutputPtr->objTrans[i].velY / 100.0f;
			algo_objInfo.trcOutData[k].velAbsX = mAlgoPerOutputPtr->objTrans[i].velAbsX / 100.0f;
			algo_objInfo.trcOutData[k].velAbsY = mAlgoPerOutputPtr->objTrans[i].velAbsY / 100.0f;
			algo_objInfo.trcOutData[k].lifeCycle = mAlgoPerOutputPtr->objTrans[i].lifeCycle;
			algo_objInfo.trcOutData[k].fTTC = mAlgoPerOutputPtr->objTrans[i].fTTC / 100.0f;
			algo_objInfo.trcOutData[k].historyMovDist = mAlgoPerOutputPtr->objTrans[i].historyMovDist;
			algo_objInfo.trcOutData[k].fDDCI = mAlgoPerOutputPtr->objTrans[i].fDDCI / 100.0f;
			++k;
		}
		algo_objInfo.trcNum = k;
	}
	// 5. 更新回灌时间，并向播放器确认该帧已接收。
	TimeStamp = msg->header.stamp.toSec();
	if (RosbagTimeStamp == 0)
	{
		algo_InitFlg = 1;
		algo_timeFrm = 0;
	}
	else if ((TimeStamp - RosbagTimeStamp) < 0)
	{
		algo_InitFlg = 1;
		algo_timeFrm = 0;
		reSetCarData();
	}
	else
	{
		algo_timeFrm = TimeStamp - RosbagTimeStamp;
		if (algo_timeFrm > 1)
			algo_InitFlg = 1;
	}
	RosbagTimeStamp = TimeStamp;
	plsySingleFrameSrv.request.radar_pos = algo_RadarPos.m_mountingPosition.radar_pos;
	plsySingleFrameSrv.request.frame_id = frame_counter;
	plsySingleFrameSrv.request.status = 0;
	(void)play_single_frame_client.call(plsySingleFrameSrv);
	algo_EgoCarInfo = mAlgoPerOutputPtr->egoCarInfoTrans;
	algo_adasEnable = mAlgoPerOutputPtr->ADASInfoTrans;
	if (is_wf_postprocess_enable)
	{
		// 6. 组装其余算法输入：BLD 信息、自车信息、ADAS 使能和本帧回灌标定补偿。
		algo_algoExtraInfo.bUseSizeByClassEnable = is_radar_class_size_enable;
		algo_algoExtraInfo.LGUDeleteNum = mAlgoPerOutputPtr->BLDInfoTrans.LGUDeleteNum;
		algo_algoExtraInfo.stLvl = mAlgoPerOutputPtr->BLDInfoTrans.stLvl;
		for (int ch = 0; ch < 8; ++ch)
		{
			// BLDInfoTrans 的 ChanPowRatio 为放大 100 倍保存的 uint16 数据。
			algo_algoExtraInfo.ChanPowRatio[ch] =
				static_cast<float>(mAlgoPerOutputPtr->BLDInfoTrans.ChanPowRatio[ch]) / 100.0f;
		}
		algo_DTCCode.selfInspFlg = true;
		BagTransTIMerge(&algo_bagData, &algo_cdi_number, algo_dotInfoC);

		// 雷达安装位姿来自节点 ROS 参数：默认由 YAML 配置；当 use_xlsx=true 且 Excel
		// 加载成功时，arbe_gui_main 会在本节点启动前用 Excel 的安装/整车参数覆盖 YAML。
		// 每帧 finalAzi/finalEle 标定补偿来自 bag 的 calibInfoTrans。
		algo_RadarPos.m_mountingPosition.radar_yaw_angle = arg_radar_yaw_angle;
		algo_RadarPos.m_mountingPosition.radar_pitch_angle = arg_radar_pitch_angle;
		algo_calibUpdateInfo.finalAziResult = mAlgoPerOutputPtr->calibInfoTrans.finalAziResult;
		algo_calibUpdateInfo.finalEleResult = mAlgoPerOutputPtr->calibInfoTrans.finalEleResult;
		algo_calibUpdateInfo.egoCarSpdCoef = mAlgoPerOutputPtr->calibInfoTrans.egoCarSpdCoef;
		algo_calibUpdateInfo.isCarSpdCoefOOR = mAlgoPerOutputPtr->isCarSpdOOR;
		// 7. 调用后处理/ADAS 算法主函数。仅保留一次有效入参打印，便于追溯 YAML/Excel
		//    配置及 bag 内的帧数据。
		static bool main_input_logged = false;
		if (!main_input_logged)
		{
			ROS_INFO("[POSTPROCESS_MAIN_INPUT] radar_id=%d radar_pos=%d dots=%d sgu=%u yaw=%.3f pitch=%.3f roll=%.3f off=(%.3f,%.3f,%.3f) orient=%d calib=(%.3f,%.3f) ego=(spd=%.3f,yaw=%.3f,gear=%u)",
					 arg_radar_id, (int)algo_RadarPos.m_mountingPosition.radar_pos,
					 algo_cdi_number, (unsigned)mAlgoPerOutputPtr->SGUNum,
					 algo_RadarPos.m_mountingPosition.radar_yaw_angle, algo_RadarPos.m_mountingPosition.radar_pitch_angle,
					 algo_RadarPos.m_mountingPosition.radar_roll_angle, algo_RadarPos.m_mountingPosition.radar_x_offset,
					 algo_RadarPos.m_mountingPosition.radar_y_offset, algo_RadarPos.m_mountingPosition.radar_z_offset,
					 (int)algo_RadarPos.m_mountingPosition.orientation,
					 algo_calibUpdateInfo.finalAziResult, algo_calibUpdateInfo.finalEleResult,
					 algo_EgoCarInfo.actual_spd, algo_EgoCarInfo.yaw_rate,
					 (unsigned)algo_EgoCarInfo.actual_gear);
			main_input_logged = true;
		}
		uint8_t taskTime = 1U;
		PostProcessMainTI(algo_InitFlg, frame_counter, algo_cdi_number, algo_dotInfoC, 0.066f, &algo_EgoCarInfo, &algo_egoCarFixPara, &algo_RadarPos,
						  &algo_objInfo, &algo_adasWarning, &algo_algoExtraInfo, &algo_adasEnable, &algo_clusterInfo, &algo_curbDBSCAN,
						  &algo_adasRoi, &algo_calibInputInfo, &algo_calibOutputInfo, &algo_calibUpdateInfo, &algo_DTCCode,
						  &algo_objEDRInfo, &algo_objTGUInfo, &algo_objELKInfo, &algo_objESSInfo, &algo_objGMWInfo,taskTime, taskTime);
		// 8. 发布算法输出的标定结果，供 GUI/EOL 客户端使用。
		PEROutput.calibUpdateInfo.finalCalibState = algo_calibUpdateInfo.finalCalibState;
		algo_InitFlg = 0;
		if (switch_type != 2)
		{
			algo_calibOutputInfo_msg.data.resize(10);
			algo_calibOutputInfo_msg.data[0] = algo_calibOutputInfo.aziResult;
			algo_calibOutputInfo_msg.data[1] = algo_calibOutputInfo.eleResult;
			algo_calibOutputInfo_msg.data[2] = static_cast<float>(algo_calibOutputInfo.calibMethod);
			algo_calibOutputInfo_msg.data[3] = static_cast<float>(algo_calibOutputInfo.finishPct);
			algo_calibOutputInfo_msg.data[4] = static_cast<float>(algo_calibOutputInfo.inCalibState);
			algo_calibOutputInfo_msg.data[5] = static_cast<float>(algo_calibOutputInfo.failureCode);
			algo_calibOutputInfo_msg.data[6] = static_cast<float>(algo_calibOutputInfo.timeCost);
			algo_calibOutputInfo_msg.data[7] = static_cast<float>(algo_calibOutputInfo.validTimeCost);
			algo_calibOutputInfo_msg.data[8] = static_cast<float>(arg_radar_id);
			algo_calibOutputInfo_msg.data[9] = 1.0f;
			calibOutputInfo_pub.publish(algo_calibOutputInfo_msg);
#if BUILDMODEL >= 2
			algo_calibUpdateInfo_msg.data.resize(16);
#else
			algo_calibUpdateInfo_msg.data.resize(13);
#endif
			algo_calibUpdateInfo_msg.data[0] = algo_calibUpdateInfo.finalAziResult;
			algo_calibUpdateInfo_msg.data[1] = algo_calibUpdateInfo.finalEleResult;
			algo_calibUpdateInfo_msg.data[2] = algo_calibUpdateInfo.egoCarSpdCoef;
			algo_calibUpdateInfo_msg.data[3] = static_cast<float>(algo_calibUpdateInfo.finalCalibState);
			algo_calibUpdateInfo_msg.data[4] = static_cast<float>(algo_calibUpdateInfo.lastRadarPos);
			algo_calibUpdateInfo_msg.data[5] = static_cast<float>(algo_calibUpdateInfo.failureCode);
			algo_calibUpdateInfo_msg.data[6] = static_cast<float>(algo_calibUpdateInfo.isOnlineValid);
			algo_calibUpdateInfo_msg.data[7] = static_cast<float>(algo_calibUpdateInfo.isFixing);
			algo_calibUpdateInfo_msg.data[8] = static_cast<float>(algo_calibUpdateInfo.isCarSpdCoefOOR);
			algo_calibUpdateInfo_msg.data[9] = static_cast<float>(algo_calibUpdateInfo.aziCalibProgressFlag);
			algo_calibUpdateInfo_msg.data[10] = static_cast<float>(algo_calibUpdateInfo.useTrackFlag);
#if BUILDMODEL >= 2
			algo_calibUpdateInfo_msg.data[11] = algo_calibUpdateInfo.validTimeAdd;
			algo_calibUpdateInfo_msg.data[12] = algo_calibUpdateInfo.validMileageAdd;
			algo_calibUpdateInfo_msg.data[13] = algo_calibUpdateInfo.mileageAdd;
			algo_calibUpdateInfo_msg.data[14] = static_cast<float>(arg_radar_id);
			algo_calibUpdateInfo_msg.data[15] = 1.0f;
#else
			algo_calibUpdateInfo_msg.data[11] = static_cast<float>(arg_radar_id);
			algo_calibUpdateInfo_msg.data[12] = 1.0f;
#endif
			calibUpdateInfo_pub.publish(algo_calibUpdateInfo_msg);
		}
		if (algo_calibOutputInfo.calibMethod == 4)
		{
			calib_result_msg.data.resize(15);
			calib_result_msg.data[0] = (algo_calibOutputInfo.inCalibState == 3 || algo_calibOutputInfo.inCalibState == 4);
			calib_result_msg.data[1] = algo_calibOutputInfo.finishPct;
			calib_result_msg.data[2] = (algo_calibOutputInfo.inCalibState == 4);
			calib_result_msg.data[3] = algo_calibUpdateInfo.finalAziResult;
			calib_result_msg.data[4] = algo_calibUpdateInfo.finalEleResult;
			calib_result_msg.data[5] = algo_calibUpdateInfo.failureCode;
			calib_result_msg.data[6] = 3;
			calib_result_msg.data[7] = arg_radar_id;
			calib_result_msg.data[8] = algo_calibOutputInfo.calibMethod;
			calib_result_msg.data[9] = algo_calibUpdateInfo.egoCarSpdCoef;
			calib_result_msg.data[10] = algo_calibUpdateInfo.finalCalibState;
			calib_result_msg.data[11] = algo_calibOutputInfo.inCalibState;
			calib_result_msg.data[12] = algo_calibUpdateInfo.validTimeAdd;
			calib_result_msg.data[13] = algo_calibUpdateInfo.validMileageAdd;
			calib_result_msg.data[14] = 14;
		}
		else
		{
			calib_result_msg.data.resize(15);
			calib_result_msg.data[0] = 0.0;
			calib_result_msg.data[1] = 0.0;
			calib_result_msg.data[2] = 0.0;
			calib_result_msg.data[3] = 0.0;
			calib_result_msg.data[4] = 0.0;
			calib_result_msg.data[5] = 0.0;
			calib_result_msg.data[6] = 3;
			calib_result_msg.data[7] = 0.0;
			calib_result_msg.data[8] = 0.0;
			calib_result_msg.data[9] = 0.0;
			calib_result_msg.data[10] = 0.0;
			calib_result_msg.data[11] = 0.0;
			calib_result_msg.data[14] = 14;
		}
		calibResult_pub.publish(calib_result_msg);
		if (is_eol_start)
		{
			calib_result_msg.data.resize(13);
			calib_result_msg.data[0] = (algo_calibOutputInfo.inCalibState == 3 || algo_calibOutputInfo.inCalibState == 4);
			calib_result_msg.data[1] = algo_calibOutputInfo.finishPct;
			calib_result_msg.data[2] = algo_calibOutputInfo.inCalibState;
			calib_result_msg.data[3] = algo_calibUpdateInfo.finalAziResult;
			calib_result_msg.data[4] = algo_calibUpdateInfo.finalEleResult;
			calib_result_msg.data[5] = algo_calibUpdateInfo.failureCode;
			calib_result_msg.data[6] = 0;
			calib_result_msg.data[7] = arg_radar_id;
			calib_result_msg.data[8] = (float)(algo_calibOutputInfo.validTimeCost);
			calib_result_msg.data[9] = algo_calibOutputInfo.calibMethod;
			calib_result_msg.data[10] = algo_calibUpdateInfo.egoCarSpdCoef;
			calib_result_msg.data[11] = algo_calibOutputInfo.aziResult;
			calib_result_msg.data[12] = algo_calibOutputInfo.eleResult;
			calibResult_pub.publish(calib_result_msg);
			if (algo_calibOutputInfo.inCalibState == 3 || algo_calibOutputInfo.inCalibState == 4)
			{
				is_eol_start = false;
			}
		}
		if (dyis_eol_start)
		{
			calib_result_msg.data.resize(13);
			calib_result_msg.data[0] = (algo_calibOutputInfo.inCalibState == 3 || algo_calibOutputInfo.inCalibState == 4);
			calib_result_msg.data[1] = algo_calibOutputInfo.finishPct;
			calib_result_msg.data[2] = (algo_calibOutputInfo.inCalibState == 4);
			calib_result_msg.data[3] = algo_calibUpdateInfo.finalAziResult;
			calib_result_msg.data[4] = algo_calibUpdateInfo.finalEleResult;
			calib_result_msg.data[5] = algo_calibUpdateInfo.failureCode;
			calib_result_msg.data[6] = 2;
			calib_result_msg.data[7] = arg_radar_id;
			calib_result_msg.data[8] = algo_calibOutputInfo.calibMethod;
			calib_result_msg.data[9] = algo_calibUpdateInfo.egoCarSpdCoef;
			calib_result_msg.data[10] = algo_calibOutputInfo.inCalibState;
			calib_result_msg.data[11] = algo_calibOutputInfo.aziResult;
			calib_result_msg.data[12] = algo_calibOutputInfo.eleResult;
			calibResult_pub.publish(calib_result_msg);
			if (algo_calibOutputInfo.inCalibState == 3 || algo_calibOutputInfo.inCalibState == 4)
			{
				dyis_eol_start = false;
			}
		}
		if (is_sa_calib_start)
		{
			calib_result_msg.data.resize(13);
			calib_result_msg.data[0] = algo_calibOutputInfo.inCalibState;
			calib_result_msg.data[1] = algo_calibOutputInfo.finishPct;
			calib_result_msg.data[2] = algo_calibOutputInfo.inCalibState;
			calib_result_msg.data[3] = algo_calibUpdateInfo.finalAziResult;
			calib_result_msg.data[4] = algo_calibUpdateInfo.finalEleResult;
			calib_result_msg.data[5] = algo_calibUpdateInfo.failureCode;
			calib_result_msg.data[6] = 1;
			calib_result_msg.data[7] = arg_radar_id;
			calib_result_msg.data[8] = (float)(algo_calibOutputInfo.validTimeCost);
			calib_result_msg.data[9] = algo_calibOutputInfo.calibMethod;
			calib_result_msg.data[10] = algo_calibUpdateInfo.egoCarSpdCoef;
			calib_result_msg.data[11] = algo_calibOutputInfo.aziResult;
			calib_result_msg.data[12] = algo_calibOutputInfo.eleResult;
			calibResult_pub.publish(calib_result_msg);
			if (algo_calibOutputInfo.inCalibState == 4 || algo_calibOutputInfo.inCalibState == 3)
			{
				is_sa_calib_start = false;
			}
		}
		// 9. 将算法输出的点属性回填到显示点云，再绘制目标和聚类结果。
		algo_TagtTrc_Trc_Dat_Num = algo_objInfo.trcNum;
		float cc_min, cc_max;
		Color_Coding_Min_Max::Instance()->get_values(ColoringType, cc_min, cc_max);
		j = 0;
		bool isDeleteGhost = true;
		bool isDotClean = false;
		algo_algoExtraInfo.bDotCleanEnable = false;
		for (int i = 0; i < algo_cdi_number; i++)
		{
			float finalZ = cloud_corner.points[i].z;
			if (cloud_corner.points[i].z < -arg_radar_z_offset)
			{
				finalZ = fabsf(cloud_corner.points[i].z) - 2 * arg_radar_z_offset;
			}
			cloud_corner.points[i].z = finalZ;
			cloud_corner.points[i].ghost_type = algo_dotInfoC[i].ghostRcd;
			cloud_corner.points[i].move_flag = algo_dotInfoC[i].movFlg;
			cloud_corner.points[i].vReal = algo_dotInfoC[i].velX;
			cloud_corner.points[i].cluster_id = algo_dotInfoC[i].clusterID;
			cloud_corner.points[i].curb_id = algo_dotInfoC[i].curbID;
			if (cloud_corner.points[i].ghost_type == 0)
				j++;
			if (strcmp(ColoringType.c_str(), "GhostType") == 0)
			{
				pointcloud_color_new(cloud_corner, i, cc_min, cc_max, ColoringType);
				isDeleteGhost = false;
			}
			else if (strcmp(ColoringType.c_str(), "Normal") == 0)
			{
				pointcloud_color_new(cloud_corner, i, arg_radar_id, cc_max, ColoringType);
			}
			else if (strcmp(ColoringType.c_str(), "GhostCheck") == 0)
			{
				pointcloud_color_new(cloud_corner, i, arg_radar_id, cc_max, ColoringType);
				isDeleteGhost = false;
			}
			else if (strcmp(ColoringType.c_str(), "Elevation") == 0)
			{
				pointcloud_color_new(cloud_corner, i, cc_min, cc_max, ColoringType);
			}
			else if (strcmp(ColoringType.c_str(), "DotClean") == 0)
			{
				pointcloud_color_new(cloud_corner, i, arg_radar_id, cc_max, ColoringType);
				isDotClean = true;
				algo_algoExtraInfo.bDotCleanEnable = true;
			}
			cloud_corner.points[i].track_id = algo_dotInfoC[i].objectUID;
		}
		algo_point_number = j;
		if (isDeleteGhost)
		{
			for (auto it = cloud_corner.points.begin(); it != cloud_corner.points.end();)
			{
				if (it->ghost_type != 0)
				{
					if (it->ghost_type > 100)
					{
						if (isDotClean)
							it = cloud_corner.points.erase(it);
						else
							++it;
					}
					else
					{
						it = cloud_corner.points.erase(it);
					}
				}
				else
				{
					++it;
				}
			}
			cloud_corner.width = cloud_corner.points.size();
		}
		if (is_wf_tracdisp_enable)
		{
			wf_object_display_handler();
		}
		if (is_wf_cluster_disp_enable)
		{
			wf_cluster_display_handler();
		}
		// 10. ADAS 功能使能时，发布报警状态并绘制 ADAS 区域。
		if (is_wf_adas_enable)
		{
			adas_warn_status.data.resize(16);
			adas_warn_status.data[0] = arg_radar_id;
			adas_warn_status.data[1] = algo_adasWarning.bLeftBsdWarning;
			adas_warn_status.data[2] = algo_adasWarning.bRightBsdWarning;
			adas_warn_status.data[3] = algo_adasWarning.bLeftLcaWarning;
			adas_warn_status.data[4] = algo_adasWarning.bRightLcaWarning;
			adas_warn_status.data[5] = algo_adasWarning.bLeftDowWarning;
			adas_warn_status.data[6] = algo_adasWarning.bRightDowWarning;
			adas_warn_status.data[7] = algo_adasWarning.bRcwWarning;
			adas_warn_status.data[8] = algo_adasWarning.bLeftRctaWarning;
			adas_warn_status.data[9] = algo_adasWarning.bRightRctaWarning;
			adas_warn_status.data[10] = algo_adasWarning.bLeftRctbWarning;
			adas_warn_status.data[11] = algo_adasWarning.bRightRctbWarning;
			adas_warn_status.data[12] = algo_adasWarning.bLeftFctaWarning;
			adas_warn_status.data[13] = algo_adasWarning.bRightFctaWarning;
			adas_warn_status.data[14] = algo_adasWarning.bLeftFctbWarning;
			adas_warn_status.data[15] = algo_adasWarning.bRightFctbWarning;
			wf_adas_warn_status_pub.publish(adas_warn_status);

			adas_warn_status_with_frame.data.resize(17);
			adas_warn_status_with_frame.data[0] = static_cast<uint32_t>(arg_radar_id);
			adas_warn_status_with_frame.data[1] = static_cast<uint32_t>(frame_counter);
			for (size_t i = 1; i < adas_warn_status.data.size(); ++i)
			{
				adas_warn_status_with_frame.data[i + 1] = static_cast<uint32_t>(adas_warn_status.data[i]);
			}
			wf_adas_warn_status_with_frame_pub.publish(adas_warn_status_with_frame);
			wf_adas_display_handler();
		}
		if (is_wf_adas_curb_enable)
			wf_curb_display_handler();
	}
	if (is_wf_raw_sgu_display_enable && is_wf_tracdisp_enable)
	{
		// 可与 MainTI 输出同时显示；使用 RAW_SGU 前缀和独立 Marker 命名空间区分。
		wf_raw_sgu_object_display_handler();
	}
	// 11. 目标显示或后处理关闭时，清理残留的目标 Marker。
	if ((!is_wf_tracdisp_enable) || (!is_wf_postprocess_enable))
	{
		if (wf_object_arrows.markers.size() != 0)
		{
			wf_object_arrows.markers.resize(0);
		}
		if (wf_object_referPt.markers.size() != 0)
		{
			wf_object_referPt.markers.resize(0);
		}
		if (wf_object_roadmaps_line.markers.size() != 0)
		{
			wf_object_roadmaps_line.markers.resize(0);
		}
		if (wf_object_roadmaps_point.markers.size() != 0)
		{
			wf_object_roadmaps_point.markers.resize(0);
		}
		if (wf_object_roadmapsFit_line.markers.size() != 0)
		{
			wf_object_roadmapsFit_line.markers.resize(0);
		}
		if (wf_object_roadmapsFit_point.markers.size() != 0)
		{
			wf_object_roadmapsFit_point.markers.resize(0);
		}
	}
	// 12. 按用户选择过滤静态/动态点，并发布点云。
	if (is_wf_pointcloud_enable)
	{
		if (is_wf_postprocess_enable)
		{
			if (!is_radar_dynamic_point_enable)
			{
				pcl::PointCloud<CornerRadarPointXYZRGBGeneric> static_cloud;
				for (size_t i = 0; i < cloud_corner.points.size(); ++i)
				{
					if (cloud_corner.points[i].move_flag == 0)
					{
						static_cloud.points.push_back(cloud_corner.points[i]);
					}
				}
				cloud_corner.resize(static_cloud.points.size());
				cloud_corner = static_cloud;
			}
			if (!is_radar_static_point_enable)
			{
				pcl::PointCloud<CornerRadarPointXYZRGBGeneric> dynamic_cloud;
				for (size_t i = 0; i < cloud_corner.points.size(); ++i)
				{
					if (cloud_corner.points[i].move_flag != 0)
					{
						dynamic_cloud.points.push_back(cloud_corner.points[i]);
					}
				}
				cloud_corner.resize(dynamic_cloud.points.size());
				cloud_corner = dynamic_cloud;
			}
		}
		pcl::toROSMsg(cloud_corner, output);
		output.header.frame_id = "image_radar";
		output.header.stamp = ros::Time::now();
		corner_radar_pcl_pub.publish(output);
	}
	// 13. 发布回灌帧元数据，并向播放器确认该雷达帧处理完成。
	detections_number = cloud_corner.size();
	int sign = 1;
	if (algo_EgoCarInfo.yaw_rate_sign == 1)
		sign = -1;
	radar_info_msg.data.resize(9);
	radar_info_msg.data[0] = arg_radar_id;
	radar_info_msg.data[1] = algo_EgoCarInfo.actual_spd;
	radar_info_msg.data[2] = algo_EgoCarInfo.yaw_rate * sign;
	radar_info_msg.data[3] = detections_number;
	radar_info_msg.data[4] = frame_counter;
	radar_info_msg.data[5] = algo_timeFrm * 1000;
	radar_info_msg.data[6] = mAlgoPerOutputPtr->BLDInfoTrans.bldWarningInfo.bldWarningFlag;
	radar_info_msg.data[7] = mAlgoPerOutputPtr->BLDInfoTrans.bldWarningInfo.percent;
	radar_info_msg.data[8] = mileage;
	corner_radar_info_pub.publish(radar_info_msg);
	plsySingleFrameSrv.request.radar_pos = algo_RadarPos.m_mountingPosition.radar_pos;
	plsySingleFrameSrv.request.frame_id = frame_counter;
	plsySingleFrameSrv.request.status = 1;
	(void)play_single_frame_client.call(plsySingleFrameSrv);
}
void save_algo_data_csv()
{
	std::ofstream csvfile;
	csvfile.open(algo_csv_filename, std::ios_base::app);
	if (!csvfile.is_open())
	{
		ROS_ERROR("Failed to open file: %s", algo_csv_filename.c_str());
		return;
	}
	if (frame_counter == 0)
	{
		csvfile << "frame_id,obj_id,ang\n";
	}
	for (int i = 0; i < algo_TagtTrc_Trc_Dat_Num; i++)
	{
	}
	csvfile.close();
}
void calc_Coloring()
{
	if (cloud_corner.size() > 0)
	{
		float cc_min, cc_max;
		Color_Coding_Min_Max::Instance()->get_values(ColoringType, cc_min, cc_max);
		for (int i = 0; i < cloud_corner.size(); i++)
		{
			if (strcmp(ColoringType.c_str(), "GhostType") == 0)
			{
				pointcloud_color_new(cloud_corner, i, cc_min, cc_max, ColoringType);
			}
			else if ((strcmp(ColoringType.c_str(), "Normal") == 0) || (strcmp(ColoringType.c_str(), "DotClean") == 0))
			{
				pointcloud_color_new(cloud_corner, i, arg_radar_id, cc_max, ColoringType);
			}
			else if (strcmp(ColoringType.c_str(), "GhostCheck") == 0)
			{
				pointcloud_color_new(cloud_corner, i, arg_radar_id, cc_max, ColoringType);
			}
			else if (strcmp(ColoringType.c_str(), "Elevation") == 0)
			{
				pointcloud_color_new(cloud_corner, i, cc_min, cc_max, ColoringType);
			}
			else if (strcmp(ColoringType.c_str(), "Doppler") == 0)
			{
				pointcloud_color_new(cloud_corner, i, MinDoppler, MaxDoppler, ColoringType);
			}
			else
			{
				pointcloud_one_color(cloud_corner, i, (0 + arg_radar_id * 100) % 256, (183 + arg_radar_id * 50) % 256, (235 + arg_radar_id * 50) % 256);
			}
		}
		pcl::toROSMsg(cloud_corner, output);
		output.header.frame_id = "image_radar";
		output.header.stamp = ros::Time::now();
		corner_radar_pcl_pub.publish(output);
	}
}
void wf_car_vec_data_callback(const std_msgs::Float32::ConstPtr &msg)
{
}
void calib_plate_data_callback(const std_msgs::Float32MultiArray::ConstPtr &msg)
{
	if (msg->data[0] != arg_radar_id)
	{
		return;
	}
	if (msg->data[1] == 0)
	{
		if (msg->data[2] == 1)
		{
			is_eol_start = true;
			algo_calibInputInfo.calibMethod = 3;
			algo_calibInputInfo.calibFlag = 1;
			algo_calibInputInfo.EOLStaticRange = msg->data[3];
			algo_calibInputInfo_msg.data.resize(4);
			algo_calibInputInfo_msg.data[0] = algo_calibInputInfo.calibMethod;
			algo_calibInputInfo_msg.data[1] = algo_calibInputInfo.calibFlag;
			algo_calibInputInfo_msg.data[2] = algo_calibInputInfo.EOLStaticRange;
			algo_calibInputInfo_msg.data[3] = arg_radar_id;
			calibInputInfo_pub.publish(algo_calibInputInfo_msg);
			ROS_INFO("is_eol_start:%d,range:%f", is_eol_start, algo_calibInputInfo.EOLStaticRange);
		}
		else
		{
			is_eol_start = false;
			algo_calibInputInfo.calibMethod = 3;
			algo_calibInputInfo.calibFlag = 2;
			algo_calibInputInfo_msg.data.resize(3);
			algo_calibInputInfo_msg.data[0] = algo_calibInputInfo.calibMethod;
			algo_calibInputInfo_msg.data[1] = algo_calibInputInfo.calibFlag;
			algo_calibInputInfo_msg.data[2] = arg_radar_id;
			calibInputInfo_pub.publish(algo_calibInputInfo_msg);
			ROS_INFO("is_eol_start:%d", is_eol_start);
		}
	}
	else if (msg->data[1] == 2)
	{
		if (msg->data[2] == 1)
		{
			dyis_eol_start = true;
			algo_calibInputInfo.calibMethod = 2;
			algo_calibInputInfo.calibFlag = 1;
			algo_calibInputInfo.EOLStaticRange = msg->data[3];
			algo_calibInputInfo_msg.data.resize(4);
			algo_calibInputInfo_msg.data[0] = algo_calibInputInfo.calibMethod;
			algo_calibInputInfo_msg.data[1] = algo_calibInputInfo.calibFlag;
			algo_calibInputInfo_msg.data[2] = algo_calibInputInfo.EOLStaticRange;
			algo_calibInputInfo_msg.data[3] = arg_radar_id;
			calibInputInfo_pub.publish(algo_calibInputInfo_msg);
			ROS_INFO("dyis_eol_start:%d,range:%f", is_eol_start, algo_calibInputInfo.EOLStaticRange);
		}
		else
		{
			dyis_eol_start = false;
			algo_calibInputInfo.calibMethod = 2;
			algo_calibInputInfo.calibFlag = 2;
			algo_calibInputInfo_msg.data.resize(3);
			algo_calibInputInfo_msg.data[0] = algo_calibInputInfo.calibMethod;
			algo_calibInputInfo_msg.data[1] = algo_calibInputInfo.calibFlag;
			algo_calibInputInfo_msg.data[2] = arg_radar_id;
			calibInputInfo_pub.publish(algo_calibInputInfo_msg);
			ROS_INFO("dyis_eol_start:%d", dyis_eol_start);
		}
	}
	else
	{
		is_sa_calib_start = true;
		algo_calibInputInfo.calibMethod = 1;
		algo_calibInputInfo.calibFlag = 1;
		algo_calibInputInfo_msg.data.resize(3);
		algo_calibInputInfo_msg.data[0] = algo_calibInputInfo.calibMethod;
		algo_calibInputInfo_msg.data[1] = algo_calibInputInfo.calibFlag;
		algo_calibInputInfo_msg.data[2] = arg_radar_id;
		calibInputInfo_pub.publish(algo_calibInputInfo_msg);
	}
}
void imu_targets_read_callback(const arbe_msgs::ImuOutput::ConstPtr &msg)
{
	const double vehicle_length = (algo_egoCarFixPara.vehicle_length > 0.0f) ? algo_egoCarFixPara.vehicle_length : 4.655;
	const double vehicle_width = (algo_egoCarFixPara.vehicle_width > 0.0f) ? algo_egoCarFixPara.vehicle_width : 1.89;
	const double vehicle_height = (algo_egoCarFixPara.vehicle_height > 0.0f) ? algo_egoCarFixPara.vehicle_height : 1.664;
	const double Target1HeadingDiff_offset = 0;
	wf_imu_object_boxes.markers.resize(1);
	wf_imu_object_boxes.markers[0].header.frame_id = "image_radar";
	wf_imu_object_boxes.markers[0].header.stamp = ros::Time::now();
	wf_imu_object_boxes.markers[0].ns = "imu_object";
	wf_imu_object_boxes.markers[0].id = 100;
	wf_imu_object_boxes.markers[0].type = visualization_msgs::Marker::CUBE;
	wf_imu_object_boxes.markers[0].action = visualization_msgs::Marker::ADD;
	double heading_rad = msg->Target1HeadingDiff * M_PI / 180.0;
	double dx = -vehicle_length / 2.0 * cos(heading_rad);
	double dy = -vehicle_length / 2.0 * sin(heading_rad);
	wf_imu_object_boxes.markers[0].pose.position.x = msg->Target1CoorX;
	wf_imu_object_boxes.markers[0].pose.position.y = msg->Target1CoorY;
	wf_imu_object_boxes.markers[0].pose.position.z = 0;
	tf2::Quaternion q_rot;
	double yaw_deg = msg->Target1HeadingDiff + Target1HeadingDiff_offset;
	q_rot.setRPY(0, 0, yaw_deg * M_PI / 180.0);
	q_rot = q_rot.normalize();
	wf_imu_object_boxes.markers[0].pose.orientation.x = q_rot.getX();
	wf_imu_object_boxes.markers[0].pose.orientation.y = q_rot.getY();
	wf_imu_object_boxes.markers[0].pose.orientation.z = q_rot.getZ();
	wf_imu_object_boxes.markers[0].pose.orientation.w = q_rot.getW();
	wf_imu_object_boxes.markers[0].color.r = 1;
	wf_imu_object_boxes.markers[0].color.g = 0;
	wf_imu_object_boxes.markers[0].color.b = 0;
	wf_imu_object_boxes.markers[0].color.a = 0.7;
	wf_imu_object_boxes.markers[0].lifetime = ros::Duration(0);
	wf_imu_object_boxes.markers[0].scale.x = vehicle_length;
	wf_imu_object_boxes.markers[0].scale.y = vehicle_width;
	wf_imu_object_boxes.markers[0].scale.z = vehicle_height;
	wf_bbox_pub.publish(wf_imu_object_boxes);
}
void reSetCarData()
{
	algo_EgoCarInfo.actual_spd = 0;
	algo_EgoCarInfo.yaw_rate = 0;
	algo_EgoCarInfo.yaw_rate_sign = 0;
	algo_EgoCarInfo.lat_accel = 0;
	algo_EgoCarInfo.long_accel = 0;
	algo_EgoCarInfo.steer_angle = 0;
	algo_EgoCarInfo.steer_angle_sign = 0;
	algo_EgoCarInfo.fl_whl_spd = 0;
	algo_EgoCarInfo.fr_whl_spd = 0;
	algo_EgoCarInfo.rl_whl_spd = 0;
	algo_EgoCarInfo.rr_whl_spd = 0;
}
void wf_imu_data_callback(const arbe_msgs::wfImuData::ConstPtr &msg)
{
	time_t t = time(NULL);
	struct tm tm = *localtime(&t);
	algo_GPS_data[0] = tm.tm_hour;
	algo_GPS_data[1] = tm.tm_min;
	algo_GPS_data[2] = tm.tm_sec;
	algo_GPS_data[3] = atof(msg->Imudata[GNSS_GPCHC_INDEX_SPEED].c_str());
	algo_GPS_data[4] = atof(msg->Imudata[GNSS_GPCHC_INDEX_HEADING].c_str());
	algo_GPS_data[5] = atof(msg->Imudata[GNSS_GPCHC_INDEX_PICH].c_str());
	algo_GPS_data[6] = atof(msg->Imudata[GNSS_GPCHC_INDEX_ROLL].c_str());
	algo_GPS_data[7] = atof(msg->Imudata[GNSS_GPCHC_INDEX_GRRO_X].c_str());
	algo_GPS_data[8] = atof(msg->Imudata[GNSS_GPCHC_INDEX_GRRO_Y].c_str());
	algo_GPS_data[9] = atof(msg->Imudata[GNSS_GPCHC_INDEX_GRRO_Z].c_str());
	algo_GPS_data[10] = atof(msg->Imudata[GNSS_GPCHC_INDEX_ACC_X].c_str());
	algo_GPS_data[11] = atof(msg->Imudata[GNSS_GPCHC_INDEX_ACC_Y].c_str());
	algo_GPS_data[12] = atof(msg->Imudata[GNSS_GPCHC_INDEX_ACC_Z].c_str());
}
void write_bld_event_to_csv(const std::string &type,
							float carV,
							int frame_id,
							int radar_id)
{
	if (current_csv_path.empty())
		return;
	if (!header_written && access(current_csv_path.c_str(), F_OK) == -1)
	{
		std::ofstream out(current_csv_path, std::ios::out);
		if (out.is_open())
		{
			out << "timestamp,type,carV,frame_id,radar_id,mileage\n";
			out.close();
			header_written = true;
		}
	}
	float mileage_tp = 0.0F;
	if (mileage > 0)
	{
		mileage_tp = mileage;
	}
	else
	{
		mileage_tp = mileage_calc;
	}
	std::ofstream out(current_csv_path, std::ios::app);
	if (out.is_open())
	{
		std::time_t raw_time = ros::Time::now().toSec();
		char timebuf[32];
		std::strftime(timebuf, sizeof(timebuf), "%Y-%m-%d %H:%M:%S", std::localtime(&raw_time));
		out << timebuf << "," << type << "," << carV << ","
			<< frame_id << "," << radar_id << "," << mileage_tp << "\n";
		out.close();
	}
}
void bld_warning_recording_control_callback(const std_msgs::String::ConstPtr &msg)
{
	if (msg->data == "StartRecord")
	{
		should_record_bld_warning = true;
		std::time_t now = std::time(nullptr);
		char timebuf[32];
		std::strftime(timebuf, sizeof(timebuf), "%Y%m%d_%H%M%S", std::localtime(&now));
		current_csv_path = "bld_warning_" + std::string(timebuf) + "_" + RecordFileName + ".csv";
		header_written = false;
		algo_InitFlg_recoredBLD = true;
		int radar_id = algo_RadarPos.m_mountingPosition.radar_pos;
		write_bld_event_to_csv("start", algo_EgoCarInfo.actual_spd, -1, radar_id);
		ROS_INFO_STREAM("[bld_warning] 开始记录: " << current_csv_path);
	}
	else if (msg->data == "StopRecord")
	{
		int radar_id = algo_RadarPos.m_mountingPosition.radar_pos;
		write_bld_event_to_csv("end", algo_EgoCarInfo.actual_spd, -1, radar_id);
		should_record_bld_warning = false;
		current_csv_path.clear();
		ROS_INFO("[bld_warning] 停止记录");
	}
}
void on_program_exit()
{
	if (should_record_bld_warning && !current_csv_path.empty())
	{
		int radar_id = algo_RadarPos.m_mountingPosition.radar_pos;
		write_bld_event_to_csv("end", algo_EgoCarInfo.actual_spd, -1, radar_id);
		ROS_WARN("[bld_warning] 程序退出，已自动补写 end");
	}
}
int main(int argc, char **argv)
{
	param_init_track();
	pthread_t si_slam_cam_thread_id;
	int ret;
	ros::init(argc, argv, "arbe_visualization_engine");
	std::atexit(on_program_exit);
	ros::NodeHandle n("~");
	ros::NodeHandle n_cam("~");
	ROS_INFO("USING SOURCE ALGORITHM");
	n.setCallbackQueue(&pc_disp_queue[IND_FOR_PC_MAIN]);
	n_cam.setCallbackQueue(&cam_disp_queue[IND_FOR_CAM_MAIN]);
	arg_radar_yaw_angle = 0.0;
	n.getParam("Radar_ID", arg_radar_id);
	n.getParam("Ctrl_Port", radar_index);
	n.getParam("Antenna_Name", arg_radar_name);
	n.getParam("Radar_Yaw_Angle", arg_radar_yaw_angle);
	n.getParam("Radar_Pitch_Angle", arg_radar_pitch_angle);
	double arg_radar_roll_angle = 0.0;
	n.getParam("Radar_Roll_Angle", arg_radar_roll_angle);
	n.getParam("Radar_Offset_x", arg_radar_x_offset);
	n.getParam("Radar_Offset_y", arg_radar_y_offset);
	n.getParam("Radar_Offset_z", arg_radar_z_offset);
	n.getParam("WF_Obj_FileName", fileNameWFObj);
	n.getParam("CarSpd_ego_Coef", arg_egoCarSpdCoefk_value);
	n.getParam("orientation", arg_orientation_value);
	int arg_radar_pos_value = arg_radar_id;
	n.param("radar_pos", arg_radar_pos_value, arg_radar_pos_value);
	double vehicle_length = 4.655;
	double vehicle_width = 1.8;
	double vehicle_height = 1.664;
	double vehicle_wheel_base = 3.0;
	double vehicle_wheel_track = 0.0;
	double bumper2RearAxle_dist = 3.85;
	double vehicle_chassis_height = 0.0;
	double vehicle_dist_FR = 0.0;
	double vehicle_dist_RR = 0.0;
	double wheelCircumference = 0.0;
	double vehWeight = 0.0;
	double carSpdCompensation = 0.0;
	double pillar_b_distX = 0.0;
	double rear_bumper_distX = 0.0;
	double CenterOfThe95thEyellipse = 0.0;
	n.param("vehicle_length", vehicle_length, vehicle_length);
	n.param("vehicle_width", vehicle_width, vehicle_width);
	n.param("vehicle_height", vehicle_height, vehicle_height);
	n.param("vehicle_wheel_base", vehicle_wheel_base, vehicle_wheel_base);
	n.param("vehicle_wheel_track", vehicle_wheel_track, vehicle_wheel_track);
	n.param("bumper2RearAxle_dist", bumper2RearAxle_dist, bumper2RearAxle_dist);
	n.param("vehicle_chassis_height", vehicle_chassis_height, vehicle_chassis_height);
	n.param("vehicle_dist_FR", vehicle_dist_FR, vehicle_dist_FR);
	n.param("vehicle_dist_RR", vehicle_dist_RR, vehicle_dist_RR);
	n.param("wheelCircumference", wheelCircumference, wheelCircumference);
	n.param("vehWeight", vehWeight, vehWeight);
	n.param("carSpdCompensation", carSpdCompensation, carSpdCompensation);
	n.param("pillar_b_distX", pillar_b_distX, pillar_b_distX);
	n.param("rear_bumper_distX", rear_bumper_distX, rear_bumper_distX);
	n.param("CenterOfThe95thEyellipse", CenterOfThe95thEyellipse, CenterOfThe95thEyellipse);
	algo_setAng = arg_radar_yaw_angle;
	algo_eleAng = arg_radar_pitch_angle;
	algo_RadarPos.m_mountingPosition.radar_pos = static_cast<uint8_t>(arg_radar_pos_value);
	algo_RadarPos.m_mountingPosition.radar_x_offset = arg_radar_x_offset;
	algo_RadarPos.m_mountingPosition.radar_y_offset = arg_radar_y_offset;
	algo_RadarPos.m_mountingPosition.radar_z_offset = arg_radar_z_offset;
	algo_RadarPos.m_mountingPosition.radar_yaw_angle = arg_radar_yaw_angle;
	algo_RadarPos.m_mountingPosition.radar_pitch_angle = arg_radar_pitch_angle;
	algo_RadarPos.m_mountingPosition.radar_roll_angle = arg_radar_roll_angle;
	algo_RadarPos.m_mountingPosition.orientation = arg_orientation_value;
	s_menuAziValue = arg_radar_yaw_angle;
	s_menuEleValue = arg_radar_pitch_angle;
	algo_egoCarFixPara.vehicle_length = static_cast<float>(vehicle_length);
	algo_egoCarFixPara.vehicle_width = static_cast<float>(vehicle_width);
	algo_egoCarFixPara.vehicle_height = static_cast<float>(vehicle_height);
	algo_egoCarFixPara.vehicle_wheel_base = static_cast<float>(vehicle_wheel_base);
	algo_egoCarFixPara.vehicle_wheel_track = static_cast<float>(vehicle_wheel_track);
	algo_egoCarFixPara.bumper2RearAxle_dist = static_cast<float>(bumper2RearAxle_dist);
	algo_egoCarFixPara.vehicle_chassis_height = static_cast<float>(vehicle_chassis_height);
	algo_egoCarFixPara.vehicle_dist_FR = static_cast<float>(vehicle_dist_FR);
	algo_egoCarFixPara.vehicle_dist_RR = static_cast<float>(vehicle_dist_RR);
	algo_egoCarFixPara.wheelCircumference = static_cast<float>(wheelCircumference);
	algo_egoCarFixPara.vehWeight = static_cast<float>(vehWeight);
	algo_egoCarFixPara.carSpdCompensation = static_cast<float>(carSpdCompensation);
	algo_egoCarFixPara.pillar_b_distX = static_cast<float>(pillar_b_distX);
	algo_egoCarFixPara.rear_bumper_distX = static_cast<float>(rear_bumper_distX);
	algo_egoCarFixPara.CenterOfThe95thEyellipse = static_cast<float>(CenterOfThe95thEyellipse);
	radar_yaw_angle = -arg_radar_yaw_angle * M_PI / 180;
	radar_pitch_angle = -arg_radar_pitch_angle * M_PI / 180;
	radar_x_offset = arg_radar_x_offset;
	radar_y_offset = arg_radar_y_offset;
	radar_z_offset = arg_radar_z_offset;
	calc_transform_matrix();
	slam_transform = pcl_transform;
	ros::Subscriber gui_commands_sub;
	set_pc_sub(true, true, arg_radar_id);
	ti_frame_rd_data_Sub = n.subscribe("/wf/frame_rd_data/ti/radar_" + std::to_string(arg_radar_id), 10, GetWaveID);
	arbe_pcl_pub = n.advertise<sensor_msgs::PointCloud2>("/arbe/rviz/pointcloud_" + std::to_string(arg_radar_id), 10);
	stationary_pcl_pub = n.advertise<sensor_msgs::PointCloud2>("/arbe/rviz/stationary_pointcloud_" + std::to_string(arg_radar_id), 10);
	marker_pub = n.advertise<visualization_msgs::MarkerArray>("/arbe/rviz/objects_" + std::to_string(arg_radar_id), 10);
	fs_poly_pub = n.advertise<geometry_msgs::PolygonStamped>("/arbe/rviz/fs_poly_" + std::to_string(arg_radar_id), 10);
	arbe_info_markers = n.advertise<visualization_msgs::Marker>("/arbe/rviz/floatingText_marker", 10);
	arbe_fps_pub = n.advertise<std_msgs::Int32>("/fps_monitor_" + std::to_string(arg_radar_id), 1);
	wf_bbox_pub = n.advertise<visualization_msgs::MarkerArray>("/wf/rviz/objects_" + std::to_string(arg_radar_id), 10);
	wf_bbox_arrows_pub = n.advertise<visualization_msgs::MarkerArray>("/wf/rviz/objects_arrows_" + std::to_string(arg_radar_id), 10);
	wf_bbox_referPt_pub = n.advertise<visualization_msgs::MarkerArray>("/wf/rviz/objects_referPt_" + std::to_string(arg_radar_id), 10);
	wf_bbox_roadmaps_line_pub = n.advertise<visualization_msgs::MarkerArray>("/wf/rviz/objects_roadmaps_line_" + std::to_string(arg_radar_id), 10);
	wf_bbox_roadmaps_point_pub = n.advertise<visualization_msgs::MarkerArray>("/wf/rviz/objects_roadmaps_point_" + std::to_string(arg_radar_id), 10);
	wf_bbox_roadmapsFit_line_pub = n.advertise<visualization_msgs::MarkerArray>("/wf/rviz/objects_roadmapsFit_line_" + std::to_string(arg_radar_id), 10);
	wf_bbox_roadmapsFit_point_pub = n.advertise<visualization_msgs::MarkerArray>("/wf/rviz/objects_roadmapsFit_point_" + std::to_string(arg_radar_id), 10);
	wf_bbox_tags_pub = n.advertise<visualization_msgs::MarkerArray>("/wf/rviz/objects_tags_" + std::to_string(arg_radar_id), 10);
	wf_objectlist_pub = n.advertise<arbe_msgs::wfObjectMsg>("/wf/objectlist_" + std::to_string(arg_radar_id), 10);
	wf_cluster_bbox_pub = n.advertise<visualization_msgs::MarkerArray>("/wf/rviz/clusters_" + std::to_string(arg_radar_id), 10);
	wf_bsd_area_pub = n.advertise<visualization_msgs::MarkerArray>("/corner_radar/rviz/BsdArea_" + std::to_string(arg_radar_id), 10);
	wf_lca_area_pub = n.advertise<visualization_msgs::MarkerArray>("/corner_radar/rviz/LcaArea_" + std::to_string(arg_radar_id), 10);
	wf_dow_area_pub = n.advertise<visualization_msgs::MarkerArray>("/corner_radar/rviz/DowArea_" + std::to_string(arg_radar_id), 10);
	wf_rcw_area_pub = n.advertise<visualization_msgs::MarkerArray>("/corner_radar/rviz/RcwArea_" + std::to_string(arg_radar_id), 10);
	wf_rcta_area_pub = n.advertise<visualization_msgs::MarkerArray>("/corner_radar/rviz/RctaArea_" + std::to_string(arg_radar_id), 10);
	wf_fcta_area_pub = n.advertise<visualization_msgs::MarkerArray>("/corner_radar/rviz/FctaArea_" + std::to_string(arg_radar_id), 10);
	wf_curb_area_pub = n.advertise<visualization_msgs::MarkerArray>("/corner_radar/rviz/Curb_" + std::to_string(arg_radar_id), 10);
	wf_adas_warn_status_pub = n.advertise<std_msgs::UInt8MultiArray>("/corner_radar/warning_status", 10);
	wf_adas_warn_status_with_frame_pub = n.advertise<std_msgs::UInt32MultiArray>("/corner_radar/warning_status_with_frame", 10);
	radars_installation_params_sub = n.subscribe("/arbe/settings/radars_installation_params", 1, radars_installation_params_callback);
	gui_controls_sub = n.subscribe("/arbe/settings/gui_controls", 100, gui_controls_callback);
	slam_active_sub = n.subscribe("/arbe/settings/enable_slam", 1, slam_enable_callback);
	enable_legacy_pc_inject_sub = n.subscribe("/arbe/settings/enable_legacy_pc_inject", 1, legacy_pc_inject_enable_cllback);
	extra_time_single_color_sub = n.subscribe("/arbe/visualization/extra_time_single_color", 10, single_color_callback);
	set_disp_objects(true);
	gui_commands_sub = n.subscribe("/arbe/settings/gui_commands", 10, gui_message_callback);
	FS_road_inclination_sub = n.subscribe("/arbe/processed/road_inclination/" + std::to_string(arg_radar_id), 3, road_inclination_callback);
	disp_FS_on_pc_sub = n.subscribe("/arbe/settings/disp_fs_on_pc", 1, choose_fs_disp_callback);
	installation_error_fix_sub = n.subscribe("/arbe/settings/installation_error_ang/0", 3, fix_installation_callback);
	restore_defaults_sub = n.subscribe("/arbe/settings/restore_defaults", 1, restore_defaults_callback);
	floating_text_angle_sub = n.subscribe("/arbe/settings/floating_text_phi", 10, change_text_phi_callback);
	imu_data_Sub = n.subscribe("/wf/huace_imu_data", 10, wf_imu_data_callback);
	car_vec_data_Sub = n.subscribe("/wf/car_vec/parsed", 10, wf_car_vec_data_callback);
	ti_RD_data_Sub = n.subscribe("/wf/corner_radar/rd_data_" + std::to_string(arg_radar_id), 10, rd_data_read_callback);
	corner_radar_controls_Sub = n.subscribe("/corner_radar/settings/radar_controls", 10, corner_radar_controls_read_callback);
	egoCarSpdCoef_Sub = n.subscribe("/ego_car_speed_coef", 10, egoCarSpdCoef_callback);
	daisch_imu_data_Sub = n.subscribe("/wf/imu_data/parsed", 10, imu_targets_read_callback);
	corner_radar_pcl_pub = n.advertise<sensor_msgs::PointCloud2>("/wf/corner_radar/rviz/pointcloud_" + std::to_string(arg_radar_id), 10);
	corner_radar_algo_pub = n.advertise<std_msgs::Float32MultiArray>("/wf/corner_radar/algo/imu_" + std::to_string(arg_radar_id), 10);
	corner_radar_info_pub = n.advertise<std_msgs::Float32MultiArray>("/corner_radar/radar_info", 10);
	bld_warning_info_pub = n.advertise<std_msgs::Float64MultiArray>("/corner_radar/bld_warning_" + std::to_string(arg_radar_id), 10);
	play_single_frame_client = n.serviceClient<wf_srvs_rvizbag::PlaySingleFrame>("/play_single_frame_" + std::to_string(arg_radar_id));
	calibResult_pub = n.advertise<std_msgs::Float32MultiArray>("/corner_radar/settings/calib_result", 10);
	calibInputInfo_pub = n.advertise<std_msgs::Float32MultiArray>("/corner_radar/calibInputInfo", 10);
	calibOutputInfo_pub = n.advertise<std_msgs::Float32MultiArray>("/corner_radar/calibOutputInfo", 10);
	calibUpdateInfo_pub = n.advertise<std_msgs::Float32MultiArray>("/corner_radar/calibUpdateInfo", 10);
	calibPlateData_sub = n.subscribe("/corner_radar/settings/calib_plate_data", 10, calib_plate_data_callback);
	bcalibPlateData_sub = n.subscribe<std_msgs::Float32MultiArray>("/corner_radar/settings/type", 10, calib_type_callback);
	set_disp_FS(true);
	arbe_msgs::arbeCameraInstallationParams::Ptr cam_params = cam_transform_defaults();
	calc_camera_transform(cam_params);
	prepare_basic_markers();
	sleep(1);
	n.getParam("enable_gui", enable_gui);
	if (enable_gui == false)
	{
		slam_enable_pub = n.advertise<arbe_msgs::arbeBoolWithTime>("/arbe/settings/enable_slam", 10, true);
		free_space_enable_pub = n.advertise<arbe_msgs::arbeBoolWithTime>("/arbe/free_space/enable", 10, true);
		ROS_INFO("Arbe real-time AI is enabled");
		arbe_msgs::arbeBoolWithTime def_msg;
		def_msg.flag = true;
		def_msg.header.stamp = ros::Time::now();
		slam_enable_pub.publish(def_msg);
		def_msg.header.stamp = ros::Time::now();
		free_space_enable_pub.publish(def_msg);
		ROS_WARN("Silent gui - always enable slam");
		set_disp_objects(true);
	}
	ros::Rate loop_rate(60);
	while (ros::ok() && (terminating == false))
	{
		handle_pc_frame();
		spin_pc_display();
		loop_rate.sleep();
	}
	return 0;
}
