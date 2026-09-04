#include "my_rviz_plugin/bag_reader.h"
#include <ros/ros.h>
#include <rosbag/view.h>
#include <std_msgs/UInt8MultiArray.h>
#include <std_msgs/String.h>
#include <common_xcp_info_publisher_rvizbag/XcpEgoInfo.h>
#include <boost/date_time/posix_time/posix_time.hpp>
#include <chrono>
#include <thread>
#include <iomanip>
#include <limits>
#include <map>
#include <sstream>
#include <cctype>

namespace
{
const int kWarningDataSize = 16;
const char* kPublicCanRearTopic = "/rear/signals";
const char* kPublicCanFrontTopic = "/front/signals";
const char* kManualTestTagTopic = "/arbe/settings/manual_test_tag";

const std::pair<int, const char*> kWarningSignalMap[] = {
  std::make_pair(1, "BSD_L"),
  std::make_pair(2, "BSD_R"),
  std::make_pair(3, "LCA_L"),
  std::make_pair(4, "LCA_R"),
  std::make_pair(5, "DOW_L"),
  std::make_pair(6, "DOW_R"),
  std::make_pair(7, "RCW"),
  std::make_pair(8, "RCTA_L"),
  std::make_pair(9, "RCTA_R"),
  std::make_pair(10, "RCTB_L"),
  std::make_pair(11, "RCTB_R"),
  std::make_pair(12, "FCTA_L"),
  std::make_pair(13, "FCTA_R"),
  std::make_pair(14, "FCTB_L"),
  std::make_pair(15, "FCTB_R"),
};

bool extractWarningData(const rosbag::MessageInstance& warning_msg, std::vector<int>& out_data)
{
  boost::shared_ptr<std_msgs::UInt8MultiArray> warning_status = warning_msg.instantiate<std_msgs::UInt8MultiArray>();
  if (!warning_status || warning_status->data.size() < static_cast<size_t>(kWarningDataSize))
  {
    return false;
  }

  out_data.assign(warning_status->data.begin(), warning_status->data.begin() + kWarningDataSize);
  return true;
}

bool hasTriggeredSignal(const std::vector<int>& warning_data)
{
  if (warning_data.size() < static_cast<size_t>(kWarningDataSize))
  {
    return false;
  }

  for (int i = 1; i < kWarningDataSize; ++i)
  {
    if (warning_data[static_cast<size_t>(i)] != 0)
    {
      return true;
    }
  }
  return false;
}

std::string radarPosName(int radar_id)
{
  switch (radar_id)
  {
    case 1:
      return "front_left";
    case 2:
      return "front_right";
    case 3:
      return "rear_left";
    case 4:
      return "rear_right";
    default:
      return "unknown";
  }
}

std::string activeSignalsToString(const std::vector<int>& warning_data)
{
  std::ostringstream ss;
  bool first = true;
  for (size_t i = 0; i < sizeof(kWarningSignalMap) / sizeof(kWarningSignalMap[0]); ++i)
  {
    const int signal_index = kWarningSignalMap[i].first;
    if (warning_data.size() <= static_cast<size_t>(signal_index))
    {
      continue;
    }
    const int signal_value = warning_data[static_cast<size_t>(signal_index)];
    if (signal_value == 0)
    {
      continue;
    }

    if (!first)
    {
      ss << "|";
    }
    first = false;
    ss << kWarningSignalMap[i].second << "=" << signal_value;
  }

  return first ? "NONE" : ss.str();
}

std::string formatRadarCount(const std::map<int, size_t>& counts)
{
  std::ostringstream ss;
  bool first = true;
  for (std::map<int, size_t>::const_iterator it = counts.begin(); it != counts.end(); ++it)
  {
    if (!first)
    {
      ss << ",";
    }
    first = false;
    ss << it->first << ":" << it->second;
  }
  return first ? "none" : ss.str();
}

std::string jsonFieldValue(const std::string& payload, const std::string& key)
{
  const std::string token = "\"" + key + "\"";
  const size_t key_pos = payload.find(token);
  if (key_pos == std::string::npos)
  {
    return "";
  }

  const size_t colon_pos = payload.find(':', key_pos + token.size());
  if (colon_pos == std::string::npos)
  {
    return "";
  }

  size_t value_pos = colon_pos + 1;
  while (value_pos < payload.size() && std::isspace(static_cast<unsigned char>(payload[value_pos])))
  {
    ++value_pos;
  }
  if (value_pos >= payload.size())
  {
    return "";
  }

  if (payload[value_pos] == '"')
  {
    ++value_pos;
    std::string out;
    bool escape = false;
    while (value_pos < payload.size())
    {
      const char c = payload[value_pos++];
      if (escape)
      {
        switch (c)
        {
          case 'n': out.push_back('\n'); break;
          case 'r': out.push_back('\r'); break;
          case 't': out.push_back('\t'); break;
          default: out.push_back(c); break;
        }
        escape = false;
        continue;
      }
      if (c == '\\')
      {
        escape = true;
        continue;
      }
      if (c == '"')
      {
        break;
      }
      out.push_back(c);
    }
    return out;
  }

  if (payload[value_pos] == '[')
  {
    const size_t end_pos = payload.find(']', value_pos);
    if (end_pos == std::string::npos)
    {
      return "";
    }
    std::string list_raw = payload.substr(value_pos + 1, end_pos - value_pos - 1);
    for (size_t i = 0; i < list_raw.size(); ++i)
    {
      if (list_raw[i] == '"')
      {
        list_raw.erase(i, 1);
        --i;
      }
    }
    std::replace(list_raw.begin(), list_raw.end(), ',', '|');
    return list_raw;
  }

  size_t end_pos = value_pos;
  while (end_pos < payload.size() && payload[end_pos] != ',' && payload[end_pos] != '}')
  {
    ++end_pos;
  }
  return payload.substr(value_pos, end_pos - value_pos);
}
}  // namespace

namespace my_rviz_plugin
{

BagReader::BagReader()
  : current_frame_(0),
    play_rate_(1.0),
    playing_(false),
    finishProcessFlag_(true),
    bPlaySPFlag_(false),
    mainRadarIndex_(3),
    play_scene_mode_(false),
    respect_bag_timing_(false),
    current_frame_published_(false),
    current_selection_radar_(-1),
    current_selection_scene_(false),
    camera_max_diff_sec_(0.1),
    state_max_age_sec_(0.2),
    warning_max_age_sec_(0.1),
    scene_lgu_max_diff_sec_(0.1)
{
  last_published_aux_indices_.fill(-1);
  last_published_scene_lgu_indices_.fill(-1);
  event_radar_pending_count_.fill(0);
  ros::param::param<double>("/frame_player/camera_max_diff_sec", camera_max_diff_sec_, 0.1);
  ros::param::param<double>("/frame_player/state_max_age_sec", state_max_age_sec_, 0.2);
  ros::param::param<double>("/frame_player/warning_max_age_sec", warning_max_age_sec_, 0.1);
  ros::param::param<double>("/frame_player/scene_lgu_max_diff_sec", scene_lgu_max_diff_sec_, 0.1);

  camera_max_diff_sec_ = std::max(0.0, camera_max_diff_sec_);
  state_max_age_sec_ = std::max(0.0, state_max_age_sec_);
  warning_max_age_sec_ = std::max(0.0, warning_max_age_sec_);
  scene_lgu_max_diff_sec_ = std::max(0.0, scene_lgu_max_diff_sec_);
}

BagReader::~BagReader()
{
  stopBag();
  bag_.close();
}

void BagReader::readBagFile(const std::string& file_path, int& frameCount0, int& frameCount1, int& frameCount2, 
int& frameCount3, int& frameCount4)
{
  if(update_progress_bar_callback_)
  {
    update_progress_bar_callback_(0.05f);
  }
  stopBag(); 

  if (bag_.isOpen()) {
    ROS_INFO("Closing previous bag file.");
    bag_.close();
  }


  if(update_progress_bar_callback_)
  {
    update_progress_bar_callback_(0.1f);
  }

  car_msgs_.clear();

  camera_msgs0_.clear();
  camera_msgs1_.clear();
  camera_msgs2_.clear();
  camera_msgs3_.clear();
  camera_msgs4_.clear();
  camera_msgs5_.clear();
  camera_msgs6_.clear();

  warning_msgs_.clear();
  manual_tag_msgs_.clear();
  public_can_ch3_msgs_.clear();
  public_can_ch2_msgs_.clear();
  xcp_front_left_msgs_.clear();
  xcp_front_right_msgs_.clear();
  xcp_rear_left_msgs_.clear();
  xcp_rear_right_msgs_.clear();

  pointcloud_msgs0_.clear();
  pointcloud_msgs1_.clear();
  pointcloud_msgs2_.clear();
  pointcloud_msgs3_.clear();
  pointcloud_msgs4_.clear();
  lgu_playback_timeline_.clear();


  empty_msgs_.clear();
  msg_flags_.clear();
  last_published_aux_indices_.fill(-1);
  last_published_scene_lgu_indices_.fill(-1);
  {
    std::lock_guard<std::mutex> lock(event_process_mutex_);
    event_radar_pending_count_.fill(0);
  }

  bag_.open(file_path, rosbag::bagmode::Read);

  if(update_progress_bar_callback_)
  {
    update_progress_bar_callback_(0.15f);
  }

  // 只读取指定的话题
  std::vector<std::string> topics = {"/wf/corner_radar/lgu_data_0","/wf/corner_radar/lgu_data_1", "/wf/corner_radar/lgu_data_2", 
    "/wf/corner_radar/lgu_data_3", "/wf/corner_radar/lgu_data_4", 
    "/cv_camera_0/image_raw/compressed","/cv_camera_1/image_raw/compressed", "/cv_camera_2/image_raw/compressed",
    "/cv_camera_3/image_raw/compressed", "/cv_camera_4/image_raw/compressed","/cv_camera_5/image_raw/compressed",
    "/cv_camera_6/image_raw/compressed",
    "/wf/car_id6/parsed2",
    "/corner_radar/warning_status_raw",
    kManualTestTagTopic,
    kPublicCanRearTopic,
    kPublicCanFrontTopic,
    "/wf/ego_car_info/front_left/parsed",
    "/wf/ego_car_info/front_right/parsed",
    "/wf/ego_car_info/rear_left/parsed",
    "/wf/ego_car_info/rear_right/parsed"
  
  };
  rosbag::View view(bag_, rosbag::TopicQuery(topics));

  // 遍历读取的消息，按话题分类存储
  if(update_progress_bar_callback_)
  {
    update_progress_bar_callback_(0.2f);
  }

  size_t count = 0;
  size_t totalCount = view.size();

  for (const auto& msg : view)
  {
    if (msg.getTopic() == "/wf/car_id6/parsed2")
    {
      car_msgs_.push_back(msg);
    }
    else if (msg.getTopic() == "/wf/corner_radar/lgu_data_0")
    {
      pointcloud_msgs0_.push_back(msg);
    }
    else if (msg.getTopic() == "/wf/corner_radar/lgu_data_1")
    {
      pointcloud_msgs1_.push_back(msg);
    }
    else if (msg.getTopic() == "/wf/corner_radar/lgu_data_2")
    {
      pointcloud_msgs2_.push_back(msg);
    }
    else if (msg.getTopic() == "/wf/corner_radar/lgu_data_3")
    {
      pointcloud_msgs3_.push_back(msg);
    }
    else if (msg.getTopic() == "/wf/corner_radar/lgu_data_4")
    {
      pointcloud_msgs4_.push_back(msg);
    }
    else if (msg.getTopic() == "/cv_camera_0/image_raw/compressed")
    {
      camera_msgs0_.push_back(msg);
    }
    else if (msg.getTopic() == "/cv_camera_1/image_raw/compressed")
    {
      camera_msgs1_.push_back(msg);
    }
    else if (msg.getTopic() == "/cv_camera_2/image_raw/compressed")
    {
      camera_msgs2_.push_back(msg);
    }
    else if (msg.getTopic() == "/cv_camera_3/image_raw/compressed")
    {
      camera_msgs3_.push_back(msg);
    }
    else if (msg.getTopic() == "/cv_camera_4/image_raw/compressed")
    {
      camera_msgs4_.push_back(msg);
    }
    else if (msg.getTopic() == "/cv_camera_5/image_raw/compressed")
    {
      camera_msgs5_.push_back(msg);
    }
    else if (msg.getTopic() == "/cv_camera_6/image_raw/compressed")
    {
      camera_msgs6_.push_back(msg);
    }
    else if (msg.getTopic() == "/corner_radar/warning_status_raw")
    {
      warning_msgs_.push_back(msg);
    }
    else if (msg.getTopic() == kManualTestTagTopic)
    {
      manual_tag_msgs_.push_back(msg);
    }
    else if (msg.getTopic() == kPublicCanRearTopic)
    {
      public_can_ch3_msgs_.push_back(msg);
    }
    else if (msg.getTopic() == kPublicCanFrontTopic)
    {
      public_can_ch2_msgs_.push_back(msg);
    }
    else if (msg.getTopic() == "/wf/ego_car_info/front_left/parsed")
    {
      xcp_front_left_msgs_.push_back(msg);
    }
    else if (msg.getTopic() == "/wf/ego_car_info/front_right/parsed")
    {
      xcp_front_right_msgs_.push_back(msg);
    }
    else if (msg.getTopic() == "/wf/ego_car_info/rear_left/parsed")
    {
      xcp_rear_left_msgs_.push_back(msg);
    }
    else if (msg.getTopic() == "/wf/ego_car_info/rear_right/parsed")
    {
      xcp_rear_right_msgs_.push_back(msg);
    }

    count++;
    if(update_progress_bar_callback_)
    {
      update_progress_bar_callback_(((float)count)/((float)totalCount) + 0.2);
    }
  }

  // 初始化当前帧为 0
  current_frame_ = 0;
  current_frame_published_ = false;

  frameCount0 = pointcloud_msgs0_.size();
  frameCount1 = pointcloud_msgs1_.size();
  frameCount2 = pointcloud_msgs2_.size();
  frameCount3 = pointcloud_msgs3_.size();
  frameCount4 = pointcloud_msgs4_.size();

  buildLguPlaybackTimeline();


  if(frameCount0>0)
  {
    empty_msgs_.push_back(pointcloud_msgs0_[0]);
  }
  else if(frameCount1>0)
  {
    empty_msgs_.push_back(pointcloud_msgs1_[0]);
  }
  else if(frameCount2>0)
  {
    empty_msgs_.push_back(pointcloud_msgs2_[0]);
  }
  else if(frameCount3>0)
  {
    empty_msgs_.push_back(pointcloud_msgs3_[0]);
  }
  else if(frameCount4>0)
  {
    empty_msgs_.push_back(pointcloud_msgs4_[0]);
  }
  for(int i=0;i<MAX_TOPIC_NUM;i++)
  msg_flags_.push_back(-1);
}

int BagReader::getMainRadarPclSize()
{
  int result = 0;

  switch (mainRadarIndex_)
  {

    case 0:
      result = pointcloud_msgs0_.size();
    break;
  case 1:
      result = pointcloud_msgs1_.size();
    break;
  case 2:
      result = pointcloud_msgs2_.size();
    break;
  case 3:
      result = pointcloud_msgs3_.size();
    break;
  case 4:
  default:
      result = pointcloud_msgs4_.size();

    break;
  }

  return result;
}

ros::Time BagReader::getMainRadarTime(int curIdx)
{
  ros::Time result;

  switch (mainRadarIndex_)
  {
    case 0:
      result = pointcloud_msgs0_[curIdx].getTime();
    break;
  case 1:
      result = pointcloud_msgs1_[curIdx].getTime();
    break;
  case 2:
      result = pointcloud_msgs2_[curIdx].getTime();
    break;
  case 3:
      result = pointcloud_msgs3_[curIdx].getTime();
    break;
  case 4:
  default:
      result = pointcloud_msgs4_[curIdx].getTime();
    break;
  }

  return result;
}

void BagReader::buildLguPlaybackTimeline()
{
  lgu_playback_timeline_.clear();

  auto append_radar = [this](int radar_id, const std::vector<rosbag::MessageInstance>& msgs) {
    for (size_t i = 0; i < msgs.size(); ++i)
    {
      LguPlaybackEvent event;
      event.bag_time = msgs[i].getTime();
      event.radar_id = radar_id;
      event.message_index = static_cast<int>(i);
      lgu_playback_timeline_.push_back(event);
    }
  };

  append_radar(0, pointcloud_msgs0_);
  append_radar(1, pointcloud_msgs1_);
  append_radar(2, pointcloud_msgs2_);
  append_radar(3, pointcloud_msgs3_);
  append_radar(4, pointcloud_msgs4_);

  std::stable_sort(lgu_playback_timeline_.begin(), lgu_playback_timeline_.end(),
                   [](const LguPlaybackEvent& lhs, const LguPlaybackEvent& rhs) {
    if (lhs.bag_time == rhs.bag_time)
    {
      return lhs.radar_id < rhs.radar_id;
    }
    return lhs.bag_time < rhs.bag_time;
  });

  ROS_INFO("[FRAME_PLAYER] built time-ordered LGU timeline: %zu messages",
           lgu_playback_timeline_.size());
}

int BagReader::getPlaybackEventCount() const
{
  return static_cast<int>(lgu_playback_timeline_.size());
}

int BagReader::getPlaybackEventRadar(int event_index) const
{
  if (event_index < 0 || event_index >= static_cast<int>(lgu_playback_timeline_.size()))
  {
    return -1;
  }
  return lgu_playback_timeline_[event_index].radar_id;
}

ros::Time BagReader::getPlaybackEventTime(int event_index) const
{
  if (event_index < 0 || event_index >= static_cast<int>(lgu_playback_timeline_.size()))
  {
    return ros::Time();
  }
  return lgu_playback_timeline_[event_index].bag_time;
}

double BagReader::getWarningMaxAgeSec() const
{
  return warning_max_age_sec_;
}

bool BagReader::preparePlaybackEvent(int event_index, bool suppress_repeated_aux)
{
  if (event_index < 0 || event_index >= static_cast<int>(lgu_playback_timeline_.size()))
  {
    return false;
  }

  std::fill(msg_flags_.begin(), msg_flags_.end(), -1);
  const LguPlaybackEvent& event = lgu_playback_timeline_[event_index];
  msg_flags_[event.radar_id] = event.message_index;

  const ros::Time selected_time = event.bag_time;
  current_selection_time_ = selected_time;
  current_selection_radar_ = event.radar_id;
  current_selection_scene_ = false;
  prepareAuxiliaryMessages(selected_time, suppress_repeated_aux);

  packetCallbackMsg();
  return true;
}

bool BagReader::prepareSceneFrame(int frame_index, bool suppress_repeated_aux)
{
  const int anchor_radar = mainRadarIndex_.load();
  const std::vector<rosbag::MessageInstance>& anchor_msgs = getMainRadarPclMsgs(anchor_radar);
  if (frame_index < 0 || frame_index >= static_cast<int>(anchor_msgs.size()))
  {
    return false;
  }

  std::fill(msg_flags_.begin(), msg_flags_.end(), -1);
  const ros::Time selected_time = anchor_msgs[frame_index].getTime();

  msg_flags_[0] = findClosestWithin(selected_time, pointcloud_msgs0_, scene_lgu_max_diff_sec_);
  msg_flags_[1] = findClosestWithin(selected_time, pointcloud_msgs1_, scene_lgu_max_diff_sec_);
  msg_flags_[2] = findClosestWithin(selected_time, pointcloud_msgs2_, scene_lgu_max_diff_sec_);
  msg_flags_[3] = findClosestWithin(selected_time, pointcloud_msgs3_, scene_lgu_max_diff_sec_);
  msg_flags_[4] = findClosestWithin(selected_time, pointcloud_msgs4_, scene_lgu_max_diff_sec_);
  msg_flags_[anchor_radar] = frame_index;

  for (int radar_id = 0; radar_id <= 4; ++radar_id)
  {
    const int selected_index = msg_flags_[radar_id];
    if (selected_index < 0)
    {
      continue;
    }
    if (suppress_repeated_aux && radar_id != anchor_radar
        && last_published_scene_lgu_indices_[radar_id] == selected_index)
    {
      msg_flags_[radar_id] = -1;
      continue;
    }
    last_published_scene_lgu_indices_[radar_id] = selected_index;
  }

  current_selection_time_ = selected_time;
  current_selection_radar_ = anchor_radar;
  current_selection_scene_ = true;
  prepareAuxiliaryMessages(selected_time, suppress_repeated_aux);

  packetCallbackMsg();
  return true;
}

void BagReader::prepareAuxiliaryMessages(const ros::Time& selected_time, bool suppress_repeated_aux)
{
  msg_flags_[5] = findLatestAtOrBefore(selected_time, warning_msgs_, warning_max_age_sec_);

  msg_flags_[6] = findClosestWithin(selected_time, camera_msgs0_, camera_max_diff_sec_);
  msg_flags_[7] = findClosestWithin(selected_time, camera_msgs1_, camera_max_diff_sec_);
  msg_flags_[8] = findClosestWithin(selected_time, camera_msgs2_, camera_max_diff_sec_);
  msg_flags_[9] = findClosestWithin(selected_time, camera_msgs3_, camera_max_diff_sec_);
  msg_flags_[10] = findClosestWithin(selected_time, camera_msgs4_, camera_max_diff_sec_);
  msg_flags_[11] = findClosestWithin(selected_time, camera_msgs5_, camera_max_diff_sec_);
  msg_flags_[20] = findClosestWithin(selected_time, camera_msgs6_, camera_max_diff_sec_);

  msg_flags_[12] = findLatestAtOrBefore(selected_time, car_msgs_, state_max_age_sec_);
  msg_flags_[13] = findLatestAtOrBefore(selected_time, xcp_front_left_msgs_, state_max_age_sec_);
  msg_flags_[14] = findLatestAtOrBefore(selected_time, xcp_front_right_msgs_, state_max_age_sec_);
  msg_flags_[15] = findLatestAtOrBefore(selected_time, xcp_rear_left_msgs_, state_max_age_sec_);
  msg_flags_[16] = findLatestAtOrBefore(selected_time, xcp_rear_right_msgs_, state_max_age_sec_);
  msg_flags_[17] = findLatestAtOrBefore(selected_time, public_can_ch3_msgs_, state_max_age_sec_);
  msg_flags_[18] = findLatestAtOrBefore(selected_time, public_can_ch2_msgs_, state_max_age_sec_);
  msg_flags_[19] = findLatestAtOrBefore(selected_time, manual_tag_msgs_, state_max_age_sec_);

  // Automatic playback may map several LGU events to the same auxiliary sample.
  // Publish that sample once; manual jump/step intentionally republishes context.
  for (int slot = 5; slot < MAX_TOPIC_NUM; ++slot)
  {
    const int selected_index = msg_flags_[slot];
    if (selected_index < 0)
    {
      continue;
    }
    if (suppress_repeated_aux && last_published_aux_indices_[slot] == selected_index)
    {
      msg_flags_[slot] = -1;
      continue;
    }
    last_published_aux_indices_[slot] = selected_index;
  }
}

int BagReader::getCurrentSelectionRadar() const
{
  return current_selection_radar_;
}

ros::Time BagReader::getCurrentSelectionTime() const
{
  return current_selection_time_;
}

bool BagReader::isCurrentSelectionScene() const
{
  return current_selection_scene_;
}

void BagReader::packetCallbackMsg()
{
  frame_msgs_.clear();

  auto push_msg = [&](const std::vector<rosbag::MessageInstance>& msgs, int index, int slot) {
    if (index >= 0 && index < static_cast<int>(msgs.size()))
    {
      frame_msgs_.push_back(msgs[index]);
      return;
    }

    ROS_ERROR("[FRAME_PLAYER] invalid message index: slot=%d index=%d size=%zu",
              slot, index, msgs.size());
    frame_msgs_.push_back(empty_msgs_[0]);
  };

  for(int i=0;i<MAX_TOPIC_NUM;i++)
  {
    if(msg_flags_[i]<0)
    {
      frame_msgs_.push_back(empty_msgs_[0]);
    }
    else
    {
      switch (i)
      {
        case 0:
          push_msg(pointcloud_msgs0_, msg_flags_[i], i);
          break;
        case 1:
          push_msg(pointcloud_msgs1_, msg_flags_[i], i);
          break;
        case 2:
          push_msg(pointcloud_msgs2_, msg_flags_[i], i);
          break;
        case 3:
          push_msg(pointcloud_msgs3_, msg_flags_[i], i);
          break;
        case 4:
          push_msg(pointcloud_msgs4_, msg_flags_[i], i);
          break;
        case 5:
          push_msg(warning_msgs_, msg_flags_[i], i);
          break;
        case 6:
          push_msg(camera_msgs0_, msg_flags_[i], i);
          break;
        case 7:
          //camera 1
          push_msg(camera_msgs1_, msg_flags_[i], i);
          break;
        case 8:
          //camera 2
          push_msg(camera_msgs2_, msg_flags_[i], i);
          break;
        case 9:
          //camera 3
          push_msg(camera_msgs3_, msg_flags_[i], i);
          break;
        case 10:
          //camera 4
          push_msg(camera_msgs4_, msg_flags_[i], i);
          break;
        case 11:
          //camera 5
          push_msg(camera_msgs5_, msg_flags_[i], i);
          break;
        case 12:
          //car
          push_msg(car_msgs_, msg_flags_[i], i);
          break;
        case 13:
          // xcp front left ego
          push_msg(xcp_front_left_msgs_, msg_flags_[i], i);
          break;
        case 14:
          // xcp front right ego
          push_msg(xcp_front_right_msgs_, msg_flags_[i], i);
          break;
        case 15:
          // xcp rear left
          push_msg(xcp_rear_left_msgs_, msg_flags_[i], i);
          break;
        case 16:
          // xcp rear right
          push_msg(xcp_rear_right_msgs_, msg_flags_[i], i);
          break;
        case 17:
          // public can rear
          push_msg(public_can_ch3_msgs_, msg_flags_[i], i);
          break;
        case 18:
          // public can front
          push_msg(public_can_ch2_msgs_, msg_flags_[i], i);
          break;
        case 19:
          // manual test tag
          push_msg(manual_tag_msgs_, msg_flags_[i], i);
          break;
        case 20:
          // camera 6
          push_msg(camera_msgs6_, msg_flags_[i], i);
          break;
        default:  
          frame_msgs_.push_back(empty_msgs_[0]);
          break;
      }
    }
  }
  
}

void BagReader::jumpToFrame(int frame_number)
{
  const int event_count = getPlaybackEventCount();

  if (frame_number >= 0 && frame_number < event_count)
  {
    play_scene_mode_ = false;
    current_frame_ = frame_number;
    if (message_callback_ && preparePlaybackEvent(current_frame_, false))
    {
      message_callback_(frame_msgs_,current_frame_,msg_flags_);
      current_frame_published_ = true;
      ROS_INFO("Playing LGU event %d/%d radar=%d", current_frame_ + 1, event_count,
               getPlaybackEventRadar(current_frame_));

    }
  }
}

void BagReader::jumpToSceneFrame(int frame_number, bool suppress_repeated_aux)
{
  const int scene_count = getMainRadarPclSize();
  if (frame_number < 0 || frame_number >= scene_count)
  {
    return;
  }

  play_scene_mode_ = true;
  current_frame_ = frame_number;
  if (message_callback_ && prepareSceneFrame(current_frame_, suppress_repeated_aux))
  {
    message_callback_(frame_msgs_, current_frame_, msg_flags_);
    current_frame_published_ = true;
    ROS_INFO("Playing debug scene %d/%d anchor_radar=%d",
             current_frame_ + 1, scene_count, mainRadarIndex_.load());
  }
}

void BagReader::playBag(bool scene_mode, bool respect_bag_timing)
{
  if (!playing_) {
      if (play_thread_.joinable()) {
            play_thread_.join();
      }
      if (play_scene_mode_.load() != scene_mode)
      {
        current_frame_ = 0;
        current_frame_published_ = false;
        last_published_scene_lgu_indices_.fill(-1);
      }
      play_scene_mode_ = scene_mode;
      respect_bag_timing_ = respect_bag_timing;
      playing_ = true;
      play_thread_ = std::thread(&BagReader::playLoop, this);
  }
}

void BagReader::stopBag() {
  if (playing_) {
      finishProcessFlag_ = true;
      playing_ = false;
      cv_.notify_all();
      event_process_cv_.notify_all();
      if (play_thread_.joinable()) {
            play_thread_.join();
      }
  }
  else if (play_thread_.joinable()) {
      play_thread_.join();
  }
  {
    std::lock_guard<std::mutex> lock(event_process_mutex_);
    event_radar_pending_count_.fill(0);
  }
}

void BagReader::setPlayRate(double rate)
{
  play_rate_ = rate;
}

void BagReader::setMessageCallback(MessageCallback callback)
{
  message_callback_ = callback;//
}

void BagReader::setUpdateProgressBarCallback(UpdateProgressBarCallback callback)
{
  update_progress_bar_callback_ = callback;
}

void BagReader::setPlaybackFinishedCallback(PlaybackFinishedCallback callback)
{
  playback_finished_callback_ = callback;
}

int BagReader::getCurrentFrame() const
{
  return current_frame_;
}

int BagReader::findClosestCameraFrame(const ros::Time& selected_time, std::vector<rosbag::MessageInstance>& camera_msgs)
{
  return findClosestWithin(selected_time, camera_msgs, camera_max_diff_sec_);
}


int BagReader::findClosestCarFrame(const ros::Time& selected_time)
{
  return findLatestAtOrBefore(selected_time, car_msgs_, state_max_age_sec_);
}

int BagReader::findClosestPtFrame(const ros::Time& selected_time, std::vector<rosbag::MessageInstance>& pcl_msgs)
{
  return findLatestAtOrBefore(selected_time, pcl_msgs, state_max_age_sec_);
}

int BagReader::findClosestWithin(const ros::Time& selected_time,
                                 const std::vector<rosbag::MessageInstance>& msgs,
                                 double max_diff_sec) const
{
  if (msgs.empty())
  {
    return -1;
  }

  auto next = std::lower_bound(msgs.begin(), msgs.end(), selected_time,
                               [](const rosbag::MessageInstance& msg, const ros::Time& time) {
    return msg.getTime() < time;
  });

  int best_index = -1;
  double best_diff = std::numeric_limits<double>::max();
  auto consider = [&](std::vector<rosbag::MessageInstance>::const_iterator it) {
    if (it == msgs.end())
    {
      return;
    }
    const double diff = std::abs((selected_time - it->getTime()).toSec());
    if (diff < best_diff)
    {
      best_diff = diff;
      best_index = static_cast<int>(std::distance(msgs.begin(), it));
    }
  };

  consider(next);
  if (next != msgs.begin())
  {
    consider(std::prev(next));
  }

  return best_diff <= max_diff_sec ? best_index : -1;
}

int BagReader::findLatestAtOrBefore(const ros::Time& selected_time,
                                    const std::vector<rosbag::MessageInstance>& msgs,
                                    double max_age_sec) const
{
  if (msgs.empty())
  {
    return -1;
  }

  auto after = std::upper_bound(msgs.begin(), msgs.end(), selected_time,
                                [](const ros::Time& time, const rosbag::MessageInstance& msg) {
    return time < msg.getTime();
  });
  if (after == msgs.begin())
  {
    return -1;
  }

  const auto latest = std::prev(after);
  const double age_sec = (selected_time - latest->getTime()).toSec();
  if (age_sec < 0.0 || age_sec > max_age_sec)
  {
    return -1;
  }
  return static_cast<int>(std::distance(msgs.begin(), latest));
}

std::vector<rosbag::MessageInstance> BagReader::getWarningMessagesAroundIndex(int center_index, double time_window_sec) const
{
  std::vector<rosbag::MessageInstance> result;

  if (center_index < 0 || center_index >= static_cast<int>(warning_msgs_.size()))
  {
    return result;
  }

  if (time_window_sec < 0.0)
  {
    time_window_sec = 0.0;
  }

  const ros::Time center_time = warning_msgs_[center_index].getTime();

  int left = center_index;
  while (left - 1 >= 0)
  {
    const double dt = std::abs((center_time - warning_msgs_[left - 1].getTime()).toSec());
    if (dt > time_window_sec)
      break;
    --left;
  }

  int right = center_index;
  while (right + 1 < static_cast<int>(warning_msgs_.size()))
  {
    const double dt = std::abs((center_time - warning_msgs_[right + 1].getTime()).toSec());
    if (dt > time_window_sec)
      break;
    ++right;
  }

  result.reserve(static_cast<size_t>(right - left + 1));
  for (int i = left; i <= right; ++i)
  {
    result.push_back(warning_msgs_[i]);
  }

  return result;
}

bool BagReader::hasWarningTopic() const
{
  return !warning_msgs_.empty();
}

size_t BagReader::getWarningCount() const
{
  return warning_msgs_.size();
}

size_t BagReader::getTriggeredWarningCount() const
{
  size_t triggered_count = 0;
  std::vector<int> warning_data;
  for (size_t i = 0; i < warning_msgs_.size(); ++i)
  {
    warning_data.clear();
    if (!extractWarningData(warning_msgs_[i], warning_data))
    {
      continue;
    }
    if (hasTriggeredSignal(warning_data))
    {
      ++triggered_count;
    }
  }
  return triggered_count;
}

bool BagReader::hasManualTagTopic() const
{
  return !manual_tag_msgs_.empty();
}

size_t BagReader::getManualTagCount() const
{
  return manual_tag_msgs_.size();
}

std::string BagReader::buildManualTagSummary(int main_radar_index, size_t max_entries) const
{
  if (manual_tag_msgs_.empty())
  {
    return "No manual test tag message in this bag.";
  }

  const std::vector<rosbag::MessageInstance>& main_msgs = getMainRadarPclMsgs(main_radar_index);
  std::ostringstream ss;
  ss << std::fixed << std::setprecision(6);
  ss << "topic=" << kManualTestTagTopic << "\n";
  ss << "tag_count=" << manual_tag_msgs_.size() << "\n";
  ss << "entry_format=msg_index|bag_time_sec|bag_time_cn|nearest_main_frame|function|result|timing|side|scene_tags|local_time|ros_time_sec\n";
  ss << "----------------------------------------\n";

  size_t display_count = manual_tag_msgs_.size();
  if (max_entries > 0 && display_count > max_entries)
  {
    display_count = max_entries;
  }

  for (size_t i = 0; i < display_count; ++i)
  {
    const rosbag::MessageInstance& msg = manual_tag_msgs_[i];
    boost::shared_ptr<std_msgs::String> tag_msg = msg.instantiate<std_msgs::String>();
    if (!tag_msg)
    {
      continue;
    }

    const std::string& payload = tag_msg->data;
    const std::string function = jsonFieldValue(payload, "function");
    const std::string result = jsonFieldValue(payload, "result");
    const std::string timing = jsonFieldValue(payload, "timing");
    const std::string side = jsonFieldValue(payload, "side");
    const std::string scene_tags = jsonFieldValue(payload, "scene_tags");
    const std::string local_time = jsonFieldValue(payload, "local_time");
    const std::string ros_time_sec = jsonFieldValue(payload, "ros_time_sec");
    const int nearest_main_frame = main_msgs.empty() ? -1 : findClosestFrameConst(msg.getTime(), main_msgs);
    const double bag_time_sec = msg.getTime().toSec();
    boost::posix_time::ptime bag_time_cn = msg.getTime().toBoost() + boost::posix_time::hours(8);

    ss << i
       << " | " << bag_time_sec
       << " | " << boost::posix_time::to_simple_string(bag_time_cn)
       << " | " << nearest_main_frame
       << " | " << (function.empty() ? "-" : function)
       << " | " << (result.empty() ? "-" : result)
       << " | " << (timing.empty() ? "-" : timing)
       << " | " << (side.empty() ? "-" : side)
       << " | " << (scene_tags.empty() ? "-" : scene_tags)
       << " | " << (local_time.empty() ? "-" : local_time)
       << " | " << (ros_time_sec.empty() ? "-" : ros_time_sec)
       << "\n";
  }

  if (display_count < manual_tag_msgs_.size())
  {
    ss << "... (" << (manual_tag_msgs_.size() - display_count) << " more)\n";
  }

  return ss.str();
}

bool BagReader::hasXcpTopic() const
{
  return !xcp_front_left_msgs_.empty() || !xcp_front_right_msgs_.empty()
      || !xcp_rear_left_msgs_.empty() || !xcp_rear_right_msgs_.empty();
}

size_t BagReader::getXcpFrontLeftCount() const
{
  return xcp_front_left_msgs_.size();
}

size_t BagReader::getXcpFrontRightCount() const
{
  return xcp_front_right_msgs_.size();
}

size_t BagReader::getXcpRearLeftCount() const
{
  return xcp_rear_left_msgs_.size();
}

size_t BagReader::getXcpRearRightCount() const
{
  return xcp_rear_right_msgs_.size();
}

std::string BagReader::buildXcpClosestSummary(int main_radar_index, int main_frame_index) const
{
  std::ostringstream ss;
  ss << std::fixed << std::setprecision(6);
  ss << "xcp_topics=/wf/ego_car_info/front_left/parsed,/wf/ego_car_info/front_right/parsed,/wf/ego_car_info/rear_left/parsed,/wf/ego_car_info/rear_right/parsed\n";
  ss << "xcp_front_left_count=" << xcp_front_left_msgs_.size() << "\n";
  ss << "xcp_front_right_count=" << xcp_front_right_msgs_.size() << "\n";
  ss << "xcp_rear_left_count=" << xcp_rear_left_msgs_.size() << "\n";
  ss << "xcp_rear_right_count=" << xcp_rear_right_msgs_.size() << "\n";

  if (!hasXcpTopic())
  {
    ss << "status=NOT_FOUND\n";
    return ss.str();
  }

  ss << "status=FOUND\n";
  const std::vector<rosbag::MessageInstance>& main_msgs = getMainRadarPclMsgs(main_radar_index);
  ss << "main_radar_index=" << main_radar_index << "\n";
  ss << "main_radar_frame_count=" << main_msgs.size() << "\n";

  if (main_msgs.empty())
  {
    ss << "status=NO_MAIN_RADAR_FRAME\n";
    return ss.str();
  }

  if (main_frame_index < 0)
  {
    main_frame_index = 0;
  }
  if (main_frame_index >= static_cast<int>(main_msgs.size()))
  {
    main_frame_index = static_cast<int>(main_msgs.size()) - 1;
  }

  const ros::Time main_time = main_msgs[static_cast<size_t>(main_frame_index)].getTime();
  ss << "selected_main_frame=" << main_frame_index << "\n";
  ss << "selected_main_time=" << main_time.toSec() << "\n";
  ss << "selection_mode=closest_one_per_side\n";
  ss << "entry_format=side,topic,msg_index,time,frame_id,actual_gear,car_spd,car_acc_xr,yaw_rate,fcta_system_state,fctb_system_state,sys_power_mod,"
        "fcta_enable,fctb_enable,steer_wheel_spd,acc_ped_pos_diag,trailer_sts,esp_diag_actv,steer_angle,esp_fun,get_rdafcta_error_status,"
        "get_rdafctb_error_status,msr_actv,vdc_actv,ptc_actv,btc_actv,ptc_actv_ra,btc_actv_ra,msr_actv_ra,drv_door_sts,passenger_door_sts,"
        "lr_door_sts,rr_door_sts,left_fcta_warning,right_fcta_warning,fcta_enable_capture,fctb_enable_capture,"
        "trc_0_obj_fcta_warning_flag,trc_0_obj_fctb_warning_flag,trc_0_dist_x,trc_0_dist_y,trc_0_vel_x,trc_0_left_fcta_flag,trc_0_right_fcta_flag,trc_0_ttc,trc_0_ddci,"
        "trc_1_obj_fcta_warning_flag,trc_1_obj_fctb_warning_flag,trc_1_dist_x,trc_1_dist_y,trc_1_vel_x,trc_1_left_fcta_flag,trc_1_right_fcta_flag,trc_1_ttc,trc_1_ddci,"
        "trc_2_obj_fcta_warning_flag,trc_2_obj_fctb_warning_flag,trc_2_dist_x,trc_2_dist_y,trc_2_vel_x,trc_2_left_fcta_flag,trc_2_right_fcta_flag,trc_2_ttc,trc_2_ddci,"
        "trc_3_obj_fcta_warning_flag,trc_3_obj_fctb_warning_flag,trc_3_dist_x,trc_3_dist_y,trc_3_vel_x,trc_3_left_fcta_flag,trc_3_right_fcta_flag,trc_3_ttc,trc_3_ddci,"
        "dt_to_main_ms\n";

  auto append_closest = [&ss, &main_time, this](const char* side,
                                                 const char* topic_name,
                                                 const std::vector<rosbag::MessageInstance>& msgs) {
    if (msgs.empty())
    {
      ss << side << "," << topic_name << ",-1,NOT_FOUND\n";
      return;
    }

    const int msg_index = findClosestFrameConst(main_time, msgs);
    if (msg_index < 0 || msg_index >= static_cast<int>(msgs.size()))
    {
      ss << side << "," << topic_name << ",-1,NOT_FOUND\n";
      return;
    }

    const rosbag::MessageInstance& msg_inst = msgs[static_cast<size_t>(msg_index)];
    boost::shared_ptr<common_xcp_info_publisher_rvizbag::XcpEgoInfo> xcp_msg = msg_inst.instantiate<common_xcp_info_publisher_rvizbag::XcpEgoInfo>();
    if (!xcp_msg)
    {
      ss << side << "," << topic_name << "," << msg_index << ",DECODE_FAILED\n";
      return;
    }

    const double dt_ms = std::abs((msg_inst.getTime() - main_time).toSec()) * 1000.0;
    ss << side << ","
       << topic_name << ","
       << msg_index << ","
       << msg_inst.getTime().toSec() << ","
       << xcp_msg->header.frame_id << ","
       << static_cast<int>(xcp_msg->actual_gear) << ","
       << xcp_msg->car_spd << ","
       << xcp_msg->car_acc_xr << ","
       << xcp_msg->yaw_rate << ","
       << static_cast<int>(xcp_msg->fcta_system_state) << ","
       << static_cast<int>(xcp_msg->fctb_system_state) << ","
       << static_cast<int>(xcp_msg->sys_power_mod) << ","
       << static_cast<int>(xcp_msg->fcta_enable) << ","
       << static_cast<int>(xcp_msg->fctb_enable) << ","
       << xcp_msg->steer_wheel_spd << ","
       << static_cast<int>(xcp_msg->acc_ped_pos_diag) << ","
       << static_cast<int>(xcp_msg->trailer_sts) << ","
       << static_cast<int>(xcp_msg->esp_diag_actv) << ","
       << xcp_msg->steer_angle << ","
       << static_cast<int>(xcp_msg->esp_fun) << ","
       << static_cast<int>(xcp_msg->get_rdafcta_error_status) << ","
       << static_cast<int>(xcp_msg->get_rdafctb_error_status) << ","
       << static_cast<int>(xcp_msg->msr_actv) << ","
       << static_cast<int>(xcp_msg->vdc_actv) << ","
       << static_cast<int>(xcp_msg->ptc_actv) << ","
       << static_cast<int>(xcp_msg->btc_actv) << ","
       << static_cast<int>(xcp_msg->ptc_actv_ra) << ","
       << static_cast<int>(xcp_msg->btc_actv_ra) << ","
       << static_cast<int>(xcp_msg->msr_actv_ra) << ","
       << static_cast<int>(xcp_msg->drv_door_sts) << ","
       << static_cast<int>(xcp_msg->passenger_door_sts) << ","
       << static_cast<int>(xcp_msg->lr_door_sts) << ","
       << static_cast<int>(xcp_msg->rr_door_sts) << ","
       << static_cast<int>(xcp_msg->left_fcta_warning) << ","
       << static_cast<int>(xcp_msg->right_fcta_warning) << ","
       << static_cast<int>(xcp_msg->fcta_enable_capture) << ","
       << static_cast<int>(xcp_msg->fctb_enable_capture) << ","
       << static_cast<int>(xcp_msg->trc_0_obj_fcta_warning_flag) << ","
       << static_cast<int>(xcp_msg->trc_0_obj_fctb_warning_flag) << ","
       << xcp_msg->trc_0_dist_x << ","
       << xcp_msg->trc_0_dist_y << ","
       << xcp_msg->trc_0_vel_x << ","
       << static_cast<int>(xcp_msg->trc_0_left_fcta_flag) << ","
       << static_cast<int>(xcp_msg->trc_0_right_fcta_flag) << ","
       << xcp_msg->trc_0_ttc << ","
       << xcp_msg->trc_0_ddci << ","
       << static_cast<int>(xcp_msg->trc_1_obj_fcta_warning_flag) << ","
       << static_cast<int>(xcp_msg->trc_1_obj_fctb_warning_flag) << ","
       << xcp_msg->trc_1_dist_x << ","
       << xcp_msg->trc_1_dist_y << ","
       << xcp_msg->trc_1_vel_x << ","
       << static_cast<int>(xcp_msg->trc_1_left_fcta_flag) << ","
       << static_cast<int>(xcp_msg->trc_1_right_fcta_flag) << ","
       << xcp_msg->trc_1_ttc << ","
       << xcp_msg->trc_1_ddci << ","
       << static_cast<int>(xcp_msg->trc_2_obj_fcta_warning_flag) << ","
       << static_cast<int>(xcp_msg->trc_2_obj_fctb_warning_flag) << ","
       << xcp_msg->trc_2_dist_x << ","
       << xcp_msg->trc_2_dist_y << ","
       << xcp_msg->trc_2_vel_x << ","
       << static_cast<int>(xcp_msg->trc_2_left_fcta_flag) << ","
       << static_cast<int>(xcp_msg->trc_2_right_fcta_flag) << ","
       << xcp_msg->trc_2_ttc << ","
       << xcp_msg->trc_2_ddci << ","
       << static_cast<int>(xcp_msg->trc_3_obj_fcta_warning_flag) << ","
       << static_cast<int>(xcp_msg->trc_3_obj_fctb_warning_flag) << ","
       << xcp_msg->trc_3_dist_x << ","
       << xcp_msg->trc_3_dist_y << ","
       << xcp_msg->trc_3_vel_x << ","
       << static_cast<int>(xcp_msg->trc_3_left_fcta_flag) << ","
       << static_cast<int>(xcp_msg->trc_3_right_fcta_flag) << ","
       << xcp_msg->trc_3_ttc << ","
       << xcp_msg->trc_3_ddci << ","
       << dt_ms << "\n";
  };

  append_closest("front_left", "/wf/ego_car_info/front_left/parsed", xcp_front_left_msgs_);
  append_closest("front_right", "/wf/ego_car_info/front_right/parsed", xcp_front_right_msgs_);
  append_closest("rear_left", "/wf/ego_car_info/rear_left/parsed", xcp_rear_left_msgs_);
  append_closest("rear_right", "/wf/ego_car_info/rear_right/parsed", xcp_rear_right_msgs_);

  return ss.str();
}

const std::vector<rosbag::MessageInstance>& BagReader::getMainRadarPclMsgs(int main_radar_index) const
{
  switch (main_radar_index)
  {
    case 0:
      return pointcloud_msgs0_;
    case 1:
      return pointcloud_msgs1_;
    case 2:
      return pointcloud_msgs2_;
    case 3:
      return pointcloud_msgs3_;
    case 4:
    default:
      return pointcloud_msgs4_;
  }
}

int BagReader::findClosestFrameConst(const ros::Time& selected_time, const std::vector<rosbag::MessageInstance>& msgs) const
{
  int closest_index = -1;
  double min_diff = std::numeric_limits<double>::max();

  for (size_t i = 0; i < msgs.size(); ++i)
  {
    const double time_diff = std::abs((selected_time - msgs[i].getTime()).toSec());
    if (time_diff < min_diff)
    {
      min_diff = time_diff;
      closest_index = static_cast<int>(i);
    }
  }

  return closest_index;
}

std::string BagReader::buildWarningSummary(int main_radar_index, size_t max_entries) const
{
  const std::vector<rosbag::MessageInstance>& main_msgs = getMainRadarPclMsgs(main_radar_index);
  if (warning_msgs_.empty() || main_msgs.empty())
  {
    return "无触发报警区间";
  }

  std::vector<std::vector<int> > signal_trigger_frames(15);
  std::vector<int> warning_data;

  for (size_t i = 0; i < warning_msgs_.size(); ++i)
  {
    warning_data.clear();
    if (!extractWarningData(warning_msgs_[i], warning_data))
    {
      continue;
    }

    if (!hasTriggeredSignal(warning_data))
    {
      continue;
    }

    const int nearest_main_frame = findClosestFrameConst(warning_msgs_[i].getTime(), main_msgs);
    if (nearest_main_frame < 0)
    {
      continue;
    }

    for (int signal_idx = 1; signal_idx < kWarningDataSize; ++signal_idx)
    {
      if (warning_data[static_cast<size_t>(signal_idx)] != 0)
      {
        signal_trigger_frames[static_cast<size_t>(signal_idx - 1)].push_back(nearest_main_frame);
      }
    }
  }

  std::ostringstream ss;
  bool has_any_output = false;
  for (size_t signal_i = 0; signal_i < signal_trigger_frames.size(); ++signal_i)
  {
    std::vector<int>& frames = signal_trigger_frames[signal_i];
    if (frames.empty())
    {
      continue;
    }

    std::sort(frames.begin(), frames.end());
    frames.erase(std::unique(frames.begin(), frames.end()), frames.end());

    std::vector<std::pair<int, int> > intervals;
    int start_frame = frames[0];
    int prev_frame = frames[0];
    for (size_t i = 1; i < frames.size(); ++i)
    {
      const int cur_frame = frames[i];
      if (cur_frame == prev_frame + 1)
      {
        prev_frame = cur_frame;
        continue;
      }
      intervals.push_back(std::make_pair(start_frame, prev_frame));
      start_frame = cur_frame;
      prev_frame = cur_frame;
    }
    intervals.push_back(std::make_pair(start_frame, prev_frame));

    if (has_any_output)
    {
      ss << "\n";
    }
    has_any_output = true;

    ss << kWarningSignalMap[signal_i].second << ": ";

    size_t display_count = intervals.size();
    if (max_entries > 0 && display_count > max_entries)
    {
      display_count = max_entries;
    }

    for (size_t i = 0; i < display_count; ++i)
    {
      if (i != 0)
      {
        ss << ", ";
      }
      const int seg_start = intervals[i].first;
      const int seg_end = intervals[i].second;
      if (seg_start == seg_end)
      {
        ss << seg_start;
      }
      else
      {
        ss << seg_start << "-" << seg_end;
      }
    }
    if (display_count < intervals.size())
    {
      ss << ", ...";
    }
  }

  if (!has_any_output)
  {
    return "无触发报警区间";
  }

  return ss.str();
}

void BagReader::playLoop() 
{
  const bool scene_mode = play_scene_mode_.load();
  const bool respect_bag_timing = respect_bag_timing_.load();
  const int event_count = scene_mode ? getMainRadarPclSize() : getPlaybackEventCount();
  if (current_frame_published_.load())
  {
    current_frame_ = current_frame_ + 1;
  }

  bool reached_end = true;
  const int start_index = current_frame_;
  const ros::Time first_event_time = start_index < event_count
      ? (scene_mode ? getMainRadarTime(start_index) : getPlaybackEventTime(start_index))
      : ros::Time(0);
  std::chrono::steady_clock::time_point playback_wall_start =
      std::chrono::steady_clock::now();

  for (int i = current_frame_; i < event_count; ++i)
  {
    if (respect_bag_timing && play_rate_ > 0.0)
    {
      const ros::Time event_time = scene_mode ? getMainRadarTime(i) : getPlaybackEventTime(i);
      const double offset_sec = std::max(0.0, (event_time - first_event_time).toSec()) / play_rate_;
      std::chrono::steady_clock::time_point target_wall_time =
          playback_wall_start + std::chrono::duration_cast<std::chrono::steady_clock::duration>(
                                    std::chrono::duration<double>(offset_sec));
      const std::chrono::steady_clock::time_point now = std::chrono::steady_clock::now();
      if (scene_mode && i > start_index && now > target_wall_time)
      {
        // Closed-loop replay must not burst through overdue frames after a slow algorithm callback.
        playback_wall_start += now - target_wall_time;
        target_wall_time = now;
      }
      std::unique_lock<std::mutex> lock(mutex_);
      cv_.wait_until(lock, target_wall_time, [this]() { return !playing_.load(); });
    }

    {
      std::lock_guard<std::mutex> lock(mutex_);
      if (!playing_)
      {
        reached_end = false;
        break;
      }
      current_frame_ = i;
    }

    int event_radar = -1;
    if (!scene_mode)
    {
      event_radar = getPlaybackEventRadar(i);
      if (event_radar < 0 || event_radar >= static_cast<int>(event_radar_pending_count_.size()))
      {
        ROS_ERROR("[FRAME_PLAYER] invalid radar id %d for LGU event %d", event_radar, i);
        continue;
      }
      {
        std::unique_lock<std::mutex> lock(event_process_mutex_);
        const bool must_wait = event_radar_pending_count_[event_radar] > 0;
        const std::chrono::steady_clock::time_point wait_start =
            std::chrono::steady_clock::now();
        event_process_cv_.wait(lock, [this, event_radar]() {
          return !playing_.load() || event_radar_pending_count_[event_radar] == 0;
        });
        if (!playing_)
        {
          reached_end = false;
          break;
        }
        if (must_wait)
        {
          // Preserve subsequent bag intervals after a slow algorithm frame; do not burst to catch up.
          playback_wall_start += std::chrono::steady_clock::now() - wait_start;
        }
        event_radar_pending_count_[event_radar] = 1;
      }
    }

    const bool prepared = scene_mode
        ? prepareSceneFrame(current_frame_, true)
        : preparePlaybackEvent(current_frame_, true);
    if (!prepared)
    {
      ROS_ERROR("[FRAME_PLAYER] failed to prepare LGU playback event %d", current_frame_);
      if (!scene_mode)
      {
        setRadarProcessComplete(event_radar);
      }
      continue;
    }

    if (scene_mode)
    {
      finishProcessFlag_ = false;
    }
    message_callback_(frame_msgs_,current_frame_,msg_flags_);
    current_frame_published_ = true;
    if (scene_mode)
    {
      ROS_INFO("Playing debug scene %d/%d anchor_radar=%d", current_frame_ + 1,
               event_count, mainRadarIndex_.load());
    }
    else
    {
      ROS_INFO("Playing LGU event %d/%d radar=%d", current_frame_ + 1, event_count,
               getPlaybackEventRadar(current_frame_));
    }

    while (scene_mode && playing_ && !finishProcessFlag_)
    {
      std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    if (!playing_)
    {
      reached_end = false;
      break;
    }
  }

  if (!scene_mode && reached_end)
  {
    // The scheduler may reach the bag end while the last frames are still processing.
    std::unique_lock<std::mutex> lock(event_process_mutex_);
    event_process_cv_.wait(lock, [this]() {
      return !playing_.load()
          || std::none_of(event_radar_pending_count_.begin(), event_radar_pending_count_.end(),
                          [](int pending_count) { return pending_count > 0; });
    });
    if (!playing_)
    {
      reached_end = false;
    }
  }
  finishProcessFlag_ = true;
  playing_ = false;

  if (reached_end && playback_finished_callback_)
  {
    playback_finished_callback_();
  }
}

void BagReader::setFinishProcessFlag(bool flag)
{
  finishProcessFlag_ = flag;
}

void BagReader::setRadarProcessComplete(int radar_id)
{
  if (radar_id < 0 || radar_id >= static_cast<int>(event_radar_pending_count_.size()))
  {
    return;
  }
  {
    std::lock_guard<std::mutex> lock(event_process_mutex_);
    if (event_radar_pending_count_[radar_id] > 0)
    {
      --event_radar_pending_count_[radar_id];
    }
  }
  event_process_cv_.notify_all();
}


void BagReader::selectMainRadar(int index)
{
  if (index < 0 || index > 4)
  {
    return;
  }
  if (mainRadarIndex_.load() != index)
  {
    current_frame_ = 0;
    current_frame_published_ = false;
    last_published_scene_lgu_indices_.fill(-1);
  }
  mainRadarIndex_ = index;
}

} // namespace my_rviz_plugin
