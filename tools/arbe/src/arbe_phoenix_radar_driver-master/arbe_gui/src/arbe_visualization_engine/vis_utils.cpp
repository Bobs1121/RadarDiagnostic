#include "Utils.h"
#include <arbe_msgs/arbeSlamMsg.h>
#include <geometry_msgs/TwistWithCovarianceStamped.h>
#include "vis_utils.hpp"
static bool is_slam_valid = false;
static bool colorPcByTrack = false;
static bool discardOutOfElevation = false;
static bool discardMpDynDetections = false;
static bool discardBelowStreetLevel = false;
static bool displayStatLmOnly = true;
static bool applyFilterDynPc = true;
static bool aggregate_pc = false;
static bool reset_local_frame = false;
bool get_slam_valid()
{
		return is_slam_valid;
}
void set_slam_valid(bool valid)
{
		is_slam_valid = valid;
}
void set_color_pc_by_track(bool flag)
{
	colorPcByTrack = flag;
}
bool get_color_pc_by_track()
{
	return colorPcByTrack;
}
void set_discard_out_of_el_context(bool flag)
{
        discardOutOfElevation = flag;
}
bool get_discard_out_of_el_context()
{
        return discardOutOfElevation;
}
void set_discard_mp_dyn_detections(bool flag)
{
		discardMpDynDetections = flag;
}
bool get_discard_mp_dyn_detections()
{
		return discardMpDynDetections;
}
void set_discard_below_street_level(bool flag)
{
		discardBelowStreetLevel = flag;
}
bool get_discard_below_street_level()
{
		return discardBelowStreetLevel;
}
void set_display_stat_LM_only(bool flag)
{
        displayStatLmOnly = flag;
}
bool get_display_stat_LM_only()
{
        return displayStatLmOnly;
}
void set_apply_filter_dyn_pc(bool flag)
{
    applyFilterDynPc = flag;
}
bool get_apply_filter_dyn_pc()
{
    return applyFilterDynPc;
}
void set_reset_mapping(bool flag)
{
        reset_local_frame = flag;
}
bool get_reset_mapping()
{
        return reset_local_frame;
}