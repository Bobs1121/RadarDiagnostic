#include "arbe_points_publisher/arbe_points_publisher.hpp"
#include <rviz/default_plugin/tools/selection_tool.h>
#include <rviz/selection/selection_manager.h>
#include <rviz/display_context.h>
#include <rviz/visualization_manager.h>
#include <sensor_msgs/PointCloud2.h>
#include <rviz/selection/forwards.h>
#include <rviz/selection/selection_handler.h>
#include <rviz/properties/property_tree_model.h>
namespace rviz_plugin_arbe_points_publisher
{
ArbePointsPublisher::ArbePointsPublisher()
{
	updateTopic();
}
ArbePointsPublisher::~ArbePointsPublisher()
{
}
void ArbePointsPublisher::updateTopic()
{
	node_handle_.param("frame_id", tf_frame_, std::string("/base_link"));
	rviz_cloud_topic_ = std::string("/arbe/rviz/selected_points");
	rviz_selected_publisher_ = node_handle_.advertise<sensor_msgs::PointCloud2>(rviz_cloud_topic_.c_str(), 1);
	selected_data_msg.header.frame_id = "image_radar";
	selected_point_pub = node_handle_.advertise<arbe_msgs::wfSelectedDataMsg>("/corner_radar/selected_points", 1);
	num_selected_points_ = 0;
}
int ArbePointsPublisher::processKeyEvent(QKeyEvent* event, rviz::RenderPanel* panel)
{
	if (event->type() == QKeyEvent::KeyPress)
	{
		if (event->key() == 'c' || event->key() == 'C')
		{
			ROS_INFO_STREAM_NAMED("ArbePointsPublisher::processKeyEvent", "Cleaning previous selection (selected area "
						                                        "and points).");
			rviz::SelectionManager* selection_manager = context_->getSelectionManager();
			rviz::M_Picked selection = selection_manager->getSelection();
			selection_manager->removeSelection(selection);
			visualization_msgs::Marker marker;
			marker.header.frame_id = context_->getFixedFrame().toStdString().c_str();
			marker.header.stamp = ros::Time::now();
			marker.ns = "basic_shapes";
			marker.id = 0;
			marker.type = visualization_msgs::Marker::CUBE;
			marker.action = visualization_msgs::Marker::DELETE;
			marker.lifetime = ros::Duration();
			num_selected_points_ = 0;
		}
		else if (event->key() == 'p' || event->key() == 'P' && ( num_selected_points_ > 0 ) )
		{
			ROS_INFO_STREAM_NAMED("ArbePointsPublisher.updateTopic",
					    "Publishing " << num_selected_points_ << " selected points to topic "
						          << node_handle_.resolveName(rviz_cloud_topic_));
		}
	}
    return 0;
}
int ArbePointsPublisher::processMouseEvent(rviz::ViewportMouseEvent& event)
{
	int flags = rviz::SelectionTool::processMouseEvent(event);
	if (event.alt())
	{
		selecting_ = false;
	}
	else
	{
		if (event.leftDown())
		{
			selecting_ = true;
		}
	}
	if (selecting_)
	{
		if (event.leftUp())
		{
			this->processSelectedArea();
		}
	}
	return flags;
}
int ArbePointsPublisher::processSelectedPoints()
{
	rviz::M_Picked selection = context_->getSelectionManager()->getSelection();
	for (const auto& pick : selection)
	{
	}
	return 0;
}
int ArbePointsPublisher::processSelectedArea()
{
	rviz::SelectionManager* selection_manager = context_->getSelectionManager();
	rviz::M_Picked selection = selection_manager->getSelection();
	rviz::PropertyTreeModel* model = selection_manager->getPropertyModel();
	rviz::FloatProperty* floatchild;
	rviz::IntProperty* uint32child;
	int i = 0;
	int point_count = 0;
	cloud.points.resize(max_selected_points);
	int selected_id,selected_radar_id =0;
	while (model->hasIndex(i, 0))
	{
		QModelIndex child_index = model->index(i, 0);
		rviz::Property* child = model->getProp(child_index);
		std::string test =child->getName().toStdString();
		std::string test1 =child->getValue().toString().toStdString();
		int numChildren =child->numChildren();
		if (child->numChildren() == num_of_pointcloud_childs )
		{
			uint32child = (rviz::IntProperty*)child->childAt(23);
			selected_id = uint32child->getValue().toInt();
			uint32child = (rviz::IntProperty*)child->childAt(24);
			selected_radar_id = uint32child->getValue().toInt();
			if (selected_radar_id == 0)
			{
				 selected_data_msg.radar0_points.push_back(selected_id);
			}
			else
			{
				selected_data_msg.radar1_points.push_back(selected_id);
			}
			point_count++;				
		}else if (child->getName().toStdString() == "Selected Points")
		{
		}
		i++;
  	}
	num_selected_points_ = point_count;
	if(point_count>0)
	{
		selected_data_msg.header.stamp = ros::Time::now();
        selected_point_pub.publish(selected_data_msg);                       
		selected_data_msg.radar0_points.clear();
		selected_data_msg.radar1_points.clear();
	}
	return 0;
}
}  
#include <pluginlib/class_list_macros.h>
PLUGINLIB_EXPORT_CLASS(rviz_plugin_arbe_points_publisher::ArbePointsPublisher, rviz::Tool)